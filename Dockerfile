# pull official base image
FROM python:3.9

# set working directory
WORKDIR /app

# build app
ADD . /app
RUN pip install -r requirements.txt

## start app
CMD ["python", "app/telemirror.py"]
