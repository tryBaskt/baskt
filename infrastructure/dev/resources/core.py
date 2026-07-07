"""Desired-state definition for Baskt's existing development resources."""

from pathlib import Path

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as event_sources,
    aws_logs as logs,
    aws_opensearchservice as opensearch,
    aws_scheduler as scheduler,
    aws_sqs as sqs,
)
from constructs import Construct


class CoreResources(Construct):
    """Currently provisioned development resources."""

    ENVIRONMENT = "dev"

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        self.stack = Stack.of(self)

        Tags.of(self).add("Application", "Baskt")
        Tags.of(self).add("Environment", self.ENVIRONMENT)
        self.tables = self._create_tables()
        self.search_domain = self._create_search_domain()
        self._create_search_indexers()
        self._create_trade_execution_worker()

    def _table(
        self,
        construct_id: str,
        *,
        table_name: str,
        partition_key: str,
        sort_key: str | None = None,
        stream: dynamodb.StreamViewType | None = None,
    ) -> dynamodb.Table:
        table = dynamodb.Table(
            self,
            construct_id,
            table_name=table_name,
            partition_key=dynamodb.Attribute(
                name=partition_key,
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=(
                dynamodb.Attribute(name=sort_key, type=dynamodb.AttributeType.STRING)
                if sort_key
                else None
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            stream=stream,
            point_in_time_recovery_specification=(
                dynamodb.PointInTimeRecoverySpecification(
                    point_in_time_recovery_enabled=True
                )
            ),
            deletion_protection=False,
            removal_policy=RemovalPolicy.RETAIN,
        )
        return table

    def _create_tables(self) -> dict[str, dynamodb.Table]:
        tables = {
            "baskt_account": self._table(
                "BasktAccountTable",
                table_name="dev_baskt_account_dynamodb",
                partition_key="cognito_user_id",
                stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            ),
            "model_portfolio": self._table(
                "ModelPortfolioTable",
                table_name="dev_model_portfolio_dynamodb",
                partition_key="portfolio_id",
                stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            ),
            "model_portfolio_follower": self._table(
                "ModelPortfolioFollowerTable",
                table_name="dev_model_portfolio_follower_dynamodb",
                partition_key="cognito_user_id",
                sort_key="portfolio_id",
            ),
            "model_portfolio_update_lock": self._table(
                "ModelPortfolioUpdateLockTable",
                table_name="dev_model_portfolio_update_lock_dynamodb",
                partition_key="portfolio_id",
            ),
            "order": self._table(
                "OrderTable",
                table_name="dev_order_dynamodb",
                partition_key="transaction_id",
                sort_key="order_id",
            ),
            "portfolio_allocation": self._table(
                "PortfolioAllocationTable",
                table_name="dev_portfolio_allocation_dynamodb",
                partition_key="cognito_user_id",
                sort_key="portfolio_id",
            ),
            "user_trade_lock": self._table(
                "UserTradeLockTable",
                table_name="dev_user_trade_lock_dynamodb",
                partition_key="cognito_user_id",
            ),
        }

        tables["baskt_account"].add_global_secondary_index(
            index_name="display_name_index",
            partition_key=dynamodb.Attribute(
                name="display_name",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        tables["model_portfolio"].add_global_secondary_index(
            index_name="portfolio_owner_cognito_user_id_index",
            partition_key=dynamodb.Attribute(
                name="portfolio_owner_cognito_user_id",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        tables["model_portfolio_follower"].add_global_secondary_index(
            index_name="portfolio_id_index",
            partition_key=dynamodb.Attribute(
                name="portfolio_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="cognito_user_id",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        tables["order"].add_global_secondary_index(
            index_name="cognito_user_id_portfolio_id_index",
            partition_key=dynamodb.Attribute(
                name="cognito_user_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="portfolio_id",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        return tables

    def _create_search_domain(self) -> opensearch.Domain:
        domain = opensearch.Domain(
            self,
            "ModelPortfolioSearchDomain",
            domain_name="dev-model-portfolio-search",
            version=opensearch.EngineVersion.OPENSEARCH_2_11,
            capacity=opensearch.CapacityConfig(
                data_node_instance_type="t3.small.search",
                data_nodes=1,
                multi_az_with_standby_enabled=False,
            ),
            ebs=opensearch.EbsOptions(
                enabled=True,
                volume_size=10,
            ),
            enforce_https=True,
            node_to_node_encryption=True,
            encryption_at_rest=opensearch.EncryptionAtRestOptions(enabled=True),
            removal_policy=RemovalPolicy.RETAIN,
            logging=opensearch.LoggingOptions(
                app_log_enabled=True,
                app_log_group=logs.LogGroup(
                    self,
                    "OpenSearchApplicationLogs",
                    retention=logs.RetentionDays.ONE_MONTH,
                    removal_policy=RemovalPolicy.RETAIN,
                ),
            ),
        )
        domain.add_access_policies(
            iam.PolicyStatement(
                principals=[iam.AccountRootPrincipal()],
                actions=["es:ESHttp*"],
                resources=[f"{domain.domain_arn}/*"],
            )
        )
        return domain

    def _search_indexer(
        self,
        construct_id: str,
        *,
        function_name: str,
        handler_directory: str,
        table: dynamodb.Table,
        index_name: str,
    ) -> lambda_.Function:
        function = lambda_.Function(
            self,
            construct_id,
            function_name=function_name,
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset(handler_directory),
            timeout=Duration.seconds(60),
            memory_size=256,
            environment={
                "OPENSEARCH_ENDPOINT": f"https://{self.search_domain.domain_endpoint}",
                "OPENSEARCH_INDEX": index_name,
                "EXPECTED_STREAM_ARN": table.table_stream_arn or "",
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        self.search_domain.grant_write(function)
        function.add_event_source(
            event_sources.DynamoEventSource(
                table,
                starting_position=lambda_.StartingPosition.LATEST,
                batch_size=100,
                bisect_batch_on_error=True,
                report_batch_item_failures=True,
                retry_attempts=3,
            )
        )
        return function

    def _create_search_indexers(self) -> None:
        base = Path(__file__).resolve().parents[1] / "lambda"
        self._search_indexer(
            "ModelPortfolioSearchIndexer",
            function_name="dev-model-portfolio-search-indexer",
            handler_directory=str(base / "model_portfolio_search"),
            table=self.tables["model_portfolio"],
            index_name="dev-model-portfolios",
        )
        self._search_indexer(
            "BasktAccountSearchIndexer",
            function_name="dev-baskt-account-search-indexer",
            handler_directory=str(base / "baskt_account_search"),
            table=self.tables["baskt_account"],
            index_name="dev-baskt-accounts",
        )

    def _create_trade_execution_worker(self) -> None:
        dead_letter_queue = sqs.Queue(
            self,
            "TradeExecutionDeadLetterQueue",
            queue_name="dev-trade-execution-dlq",
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.RETAIN,
        )
        queue = sqs.Queue(
            self,
            "TradeExecutionQueue",
            queue_name="dev-trade-execution-queue",
            visibility_timeout=Duration.seconds(180),
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                queue=dead_letter_queue,
                max_receive_count=3,
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        repo_root = Path(__file__).resolve().parents[3]
        worker = lambda_.DockerImageFunction(
            self,
            "TradeExecutionWorker",
            function_name="dev-trade-execution-queue-worker",
            code=lambda_.DockerImageCode.from_image_asset(
                directory=str(repo_root),
                file="infrastructure/dev/lambda/trade_execution_queue_worker/Dockerfile",
            ),
            architecture=lambda_.Architecture.X86_64,
            timeout=Duration.seconds(120),
            memory_size=2048,
            environment={
                "ENV": "dev",
                "ALPACA_ENV": "sandbox",
                "DEV_TRADE_EXECUTION_QUEUE_URL": queue.queue_url,
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        queue.grant_consume_messages(worker)
        for table in self.tables.values():
            table.grant_read_write_data(worker)
        worker.add_event_source(
            event_sources.SqsEventSource(
                queue,
                batch_size=10,
                enabled=False,
                report_batch_item_failures=True,
            )
        )

        controller_directory = str(
            Path(__file__).resolve().parents[1]
            / "lambda"
            / "trade_execution_queue_worker"
        )
        controller = lambda_.Function(
            self,
            "MarketHoursController",
            function_name="dev-trade-execution-market-hours-controller",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="market_hours_controller.lambda_handler",
            code=lambda_.Code.from_asset(controller_directory),
            timeout=Duration.seconds(60),
            memory_size=128,
            environment={
                "TRADE_EXECUTION_FUNCTION_NAME": worker.function_name,
                "TRADE_EXECUTION_QUEUE_ARN": queue.queue_arn,
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        worker.grant_invoke(controller)
        controller.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "lambda:ListEventSourceMappings",
                    "lambda:UpdateEventSourceMapping",
                ],
                resources=["*"],
            )


def provision(scope: Construct, state: dict[str, object]) -> None:
    """Provision this module and expose its resources to later modules."""
    resources = CoreResources(scope, "CoreResources")
    state["core"] = resources
        )

        scheduler_role = iam.Role(
            self,
            "MarketHoursSchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        controller.grant_invoke(scheduler_role)
        schedules = {
            "prepare": "cron(20-29 9 ? * MON-FRI *)",
            "open": "cron(30 9 ? * MON-FRI *)",
            "early-close": "cron(58 12 ? * MON-FRI *)",
            "close": "cron(58 15 ? * MON-FRI *)",
        }
        for action, expression in schedules.items():
            scheduler.CfnSchedule(
                self,
                f"MarketSchedule{action.title().replace('-', '')}",
                name=f"dev-trade-execution-{action}",
                flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                    mode="OFF"
                ),
                schedule_expression=expression,
                schedule_expression_timezone="America/New_York",
                target=scheduler.CfnSchedule.TargetProperty(
                    arn=controller.function_arn,
                    role_arn=scheduler_role.role_arn,
                    input=f'{{"action":"{action.replace("-", "_")}"}}',
                ),
            )
