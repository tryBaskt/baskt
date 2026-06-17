#!/usr/bin/env python3
"""
Script to create or destroy the dev_model_portfolio_dynamodb table.

Usage:
    python model_portfolio_dynamodb.py --create   # Create the table
    python model_portfolio_dynamodb.py --destroy  # Delete the table
"""

import boto3
from botocore.exceptions import ClientError
import sys
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from aws_env import load_aws_env

load_aws_env()


configurations = {
    "table_name": "dev_model_portfolio_dynamodb",
    "region": "us-east-1",
    "partition_key": "portfolio_id",
    "partition_key_attribute_type": "S",
    "partition_key_key_type": "HASH",
    "gsi": [
        {
            "gsi_name": "portfolio_owner_cognito_user_id_index",
            "gsi_partition_key": "portfolio_owner_cognito_user_id",
            "gsi_partition_key_key_type": "HASH",
            "gsi_partition_key_attribute_type": "S",

        }
    ]
}

def create_dev_model_portfolio_dynamodb():

    # Hardcoded configuration from dev-portfolios table
    TABLE_NAME = configurations["table_name"]
    REGION = configurations["region"]
    gsi_configs = configurations.get("gsi", [])
    
    # Table configuration
    table_config = {
        'TableName': TABLE_NAME,
        'AttributeDefinitions': [
            {
                'AttributeName': configurations["partition_key"],
                'AttributeType': configurations["partition_key_attribute_type"]
            }
        ] + [
            {
                'AttributeName': gsi["gsi_partition_key"],
                'AttributeType': gsi["gsi_partition_key_attribute_type"]
            }
            for gsi in gsi_configs
        ],
        'KeySchema': [
            {
                'AttributeName': configurations["partition_key"],
                'KeyType': configurations["partition_key_key_type"]
            }
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': gsi["gsi_name"],
                'KeySchema': [
                    {
                        'AttributeName': gsi["gsi_partition_key"],
                        'KeyType': gsi["gsi_partition_key_key_type"]
                    }
                ],
                'Projection': {
                    'ProjectionType': 'ALL'
                }
            }
            for gsi in gsi_configs
        ],

        'BillingMode': 'PAY_PER_REQUEST',
        'DeletionProtectionEnabled': False
    }
    
    dynamodb = boto3.client('dynamodb', region_name=REGION)
    
    try:
        print("=" * 70)
        print(f"Creating DynamoDB Table: {TABLE_NAME}")
        print("=" * 70)
        print(f"Region: {REGION}")
        print(f"Partition Key: {configurations['partition_key']} ({configurations['partition_key_attribute_type']})")
        if "sort_key" in configurations and "sort_key_attribute_type" in configurations:
            print(f"Sort Key: {configurations['sort_key']} ({configurations['sort_key_attribute_type']})")
        for gsi in gsi_configs:
            print(f"GSI: {gsi['gsi_name']} (PK: {gsi['gsi_partition_key']})")
        print(f"Billing Mode: PAY_PER_REQUEST")
        print("=" * 70)
        print()
        
        # Check if table already exists
        try:
            existing_table = dynamodb.describe_table(TableName=TABLE_NAME)
            print(f"⚠️  Table {TABLE_NAME} already exists")
            print(f"  - Table ARN: {existing_table['Table']['TableArn']}")
            print(f"  - Status: {existing_table['Table']['TableStatus']}")
            print(f"  - Item Count: {existing_table['Table'].get('ItemCount', 0)}")
            print(f"\nNo action needed. Use --destroy to delete it first if you want to recreate.")
            print("=" * 70)
            sys.exit(0)
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                # Table doesn't exist, proceed with creation
                pass
            else:
                raise
        
        print("🚀 Creating table...")
        response = dynamodb.create_table(**table_config)
        
        print(f"✓ Table creation initiated successfully")
        print(f"  - Table ARN: {response['TableDescription']['TableArn']}")
        print(f"  - Status: {response['TableDescription']['TableStatus']}")
        print(f"\n⏳ Waiting for table to become active...")
        
        # Wait for table to be created
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(
            TableName=TABLE_NAME,
            WaiterConfig={'Delay': 5, 'MaxAttempts': 25}
        )
        
        # Get final table details
        table_info = dynamodb.describe_table(TableName=TABLE_NAME)
        table = table_info['Table']
        
        print(f"\n✅ Table {TABLE_NAME} is now active!")
        print(f"  - Table ARN: {table['TableArn']}")
        print(f"  - Status: {table['TableStatus']}")
        print(f"  - Item Count: {table.get('ItemCount', 0)}")
        print("=" * 70)
        
        return response
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f"❌ Error creating table: {error_message}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        sys.exit(1)


def delete_dev_model_portfolio_dynamodb():
    """
    Delete the dev_model_portfolio_dynamodb table.
    """
    TABLE_NAME = configurations["table_name"]
    REGION = configurations["region"]
    
    dynamodb = boto3.client('dynamodb', region_name=REGION)
    
    try:
        print("=" * 70)
        print(f"Deleting DynamoDB Table: {TABLE_NAME}")
        print("=" * 70)
        print(f"Region: {REGION}")
        print("=" * 70)
        print()
        
        # Check if table exists first
        try:
            table_info = dynamodb.describe_table(TableName=TABLE_NAME)
            print(f"✓ Found table: {TABLE_NAME}")
            print(f"  - Table ARN: {table_info['Table']['TableArn']}")
            print(f"  - Status: {table_info['Table']['TableStatus']}")
            print(f"  - Item Count: {table_info['Table'].get('ItemCount', 0)}")
            print()
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"⚠️  Table {TABLE_NAME} does not exist")
                print("   Nothing to delete.")
                sys.exit(0)
            else:
                raise
        
        print("🗑️  Deleting table...")
        response = dynamodb.delete_table(TableName=TABLE_NAME)
        
        print(f"✓ Table deletion initiated")
        print(f"  - Status: {response['TableDescription']['TableStatus']}")
        print(f"\n⏳ Waiting for table to be deleted...")
        
        # Wait for table to be deleted
        waiter = dynamodb.get_waiter('table_not_exists')
        waiter.wait(
            TableName=TABLE_NAME,
            WaiterConfig={'Delay': 5, 'MaxAttempts': 25}
        )
        
        print(f"\n✅ Table {TABLE_NAME} has been deleted successfully!")
        print("=" * 70)
        
        return response
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f"❌ Error deleting table: {error_message}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        sys.exit(1)


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description=f"Create or destroy the {configurations['table_name']} DynamoDB table",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create', action='store_true', help='Create the table')
    group.add_argument('--destroy', action='store_true', help='Delete the table')
    
    args = parser.parse_args()
    
    if args.create:
        create_dev_model_portfolio_dynamodb()
    elif args.destroy:
        delete_dev_model_portfolio_dynamodb()


if __name__ == '__main__':
    main()
