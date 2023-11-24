# Define the base image. AWS provides base images for lambda with different runtimes
FROM public.ecr.aws/lambda/python:3.11

# Copy the function code and requirements file into the container
COPY lambda_function.py ${LAMBDA_TASK_ROOT}
COPY requirements.txt  ${LAMBDA_TASK_ROOT}

# Install the Python dependencies from requirements.txt
RUN pip install -r requirements.txt

# Set the CMD to your handler (could be a different file name and/or a different function)
CMD ["lambda_function.lambda_handler"]