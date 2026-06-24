FROM public.ecr.aws/lambda/python:3.12

COPY infrastructure/dev/lambda/trade_execution_queue_worker/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY backend/ ${LAMBDA_TASK_ROOT}/backend/
COPY infrastructure/dev/lambda/trade_execution_queue_worker/handler.py ${LAMBDA_TASK_ROOT}/handler.py

CMD ["handler.lambda_handler"]
