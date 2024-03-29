import os
import boto3
import botocore
import shutil
import re
import random
import datetime
import tarfile
import io
import base64
import json

# Initialize the S3 client
s3 = boto3.client('s3')
# Initialize the Firehose client
firehose_client = boto3.client('firehose')

def download_templates_from_s3(bucket_name, target_directory):
    # List objects in the S3 bucket
    objects = s3.list_objects(Bucket=bucket_name)

    for s3_object in objects.get('Contents', []):
        object_key = s3_object['Key']
        target_path = os.path.join(target_directory, object_key)
        parent_directory = os.path.dirname(target_path)
        #print(f"parent_directory is {parent_directory}")

        # Ensure that the target directory exists
        os.makedirs(parent_directory, exist_ok=True)

        # Download the S3 object to the target directory
        try:
            s3.download_file(bucket_name, object_key, target_path)
            print(f"Downloaded {object_key} to {target_path}")
        except Exception as error:
            print(f"Error while downloading file from s3: {error}")
            
    print("*** Downloading templates is done ***")

# Function to copy directories
def copy_directories(src_dir, dest_dir):
    print(f"Copying directory from {src_dir} to {dest_dir}")
    shutil.copytree(src_dir, dest_dir)
    
    print(f"*** Copying templates to {dest_dir} is done ***")

# Function to edit dates in a JSON file
def edit_dates(file_path, date_replacement, timestamp_replacement):
    print(f"Adding dates to {file_path}")

    timestamp_replacement = datetime.datetime.utcfromtimestamp(timestamp_replacement)
    with open(file_path, 'r') as f:
        #content = f.read()
        updated_content = ""
        for line in f:
            updated_line = re.sub(r'\{date\}', date_replacement, line)
            updated_line = re.sub(r'"{timestamp}"', str(int(timestamp_replacement.timestamp() * 1000)), updated_line)
            updated_content += updated_line
            timestamp_replacement += datetime.timedelta(minutes=1)

    with open(file_path, 'w') as f:
        f.write(updated_content)

def update_json_to_one_line(input_file):
    try:
        # Read the JSON content from the input file
        with open(input_file, "r") as file:
            data = json.load(file)
    
        # Convert the JSON data to a one-liner (remove line breaks and spaces)
        json_string = json.dumps(data, separators=(",", ":")) + os.linesep

        # Write the updated JSON content back to the output file
        with open(input_file, "w") as file:
            file.write(json_string)

        print(f"JSON file updated and saved to {input_file}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")

# Function to recursively traverse directories
def traverse_directories(root_dir, appfabric_bucket_name, appfabric_firehose_arn):
    for dir_path, dirs, files in os.walk(root_dir):
        #for dir_name in dirs:
            #print(f"Processing directory: {os.path.join(dir_path, dir_name)}")

        for file_name in files:
            file_path = os.path.join(dir_path, file_name)

            if file_name.endswith(".json"):
                random_number = random.randint(1, 12)
                few_days_ago = (datetime.datetime.now() - datetime.timedelta(days=random_number)).strftime("%Y-%m-%d")
                few_days_ago_dir = (datetime.datetime.now() - datetime.timedelta(days=random_number)).strftime("%Y%m%d")

                directory = os.path.dirname(file_path)
                new_dir = os.path.join(directory, few_days_ago_dir)

                if not os.path.exists(new_dir):
                    os.makedirs(new_dir)

                new_file_name = f"AuditLogs-{file_name}"
                new_file_path = os.path.join(new_dir, new_file_name)

                shutil.move(file_path, new_file_path)

                current_timestamp = int(datetime.datetime.now().timestamp())
                few_days_ago_timestamp = current_timestamp - (random_number * 24 * 60 * 60)

                edit_dates(new_file_path, few_days_ago, few_days_ago_timestamp)

                update_json_to_one_line(new_file_path)

                print(f"Creating file done: {new_file_path}")

                # If bucket name is provided, upload to S3
                if appfabric_bucket_name != 'not-defined' and appfabric_bucket_name != '':

                    s3_path = new_file_path.replace(f"{root_dir}/", "")
                    s3.upload_file(new_file_path, appfabric_bucket_name, s3_path)
                    print(f"Finished uploading to S3: {s3_path}")
                
                # If Firehose ARN is provided, push to stream
                if appfabric_firehose_arn != 'not-defined' and appfabric_firehose_arn != '':
                    
                    firehose_stream_name = appfabric_firehose_arn.split('/')[-1]
                    send_to_firehose(firehose_stream_name, new_file_path)
                    print(f"Finish streaming to Firehose: {firehose_stream_name}")
                
    print("*** Updated timestamps/dates is done ***")

def send_to_firehose(stream_name, file_path):
    try:
        # Read the JSON content from the input file
        with open(file_path, "r") as file:
            # Traverse each line in the file
            for line in file:
                # Prepare JSON record
                json_record = json.loads(line.strip())
                
                # Convert JSON record to string
                data_to_send = json.dumps(json_record)
                
                # Send the properly formatted JSON to Kinesis Firehose
                response = firehose_client.put_record(
                    DeliveryStreamName=stream_name,
                    Record={
                        'Data': data_to_send.encode('utf-8') + b'\n'
                    }
                )
            print(f"Sent to Firehose: {file_path}")
    except Exception as e:
        print(f"Error sending to Firehose: {file_path}, Error: {e}")   

def create_tmp_tarball(formatted_date):
    tmp_dir = f"/tmp/{formatted_date}/"
    tarball_name = f"/tmp/{formatted_date}.tar.gz"

    # Create a tarball (compressed archive) of the /tmp/ directory
    with tarfile.open(tarball_name, 'w:gz') as tar:
        tar.add(tmp_dir, arcname=os.path.basename(tmp_dir))

    return tarball_name

def remove_tmp_directory():
    tmp_dir = '/tmp/'
    
    try:
        for item in os.listdir(tmp_dir):
            item_path = os.path.join(tmp_dir, item)
            if os.path.isfile(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        print(f"Removed {tmp_dir}")
    except Exception as e:
        print(f"Error while removing {tmp_dir}: {str(e)}")

def handler(event, context):
    print("App Version: " + os.environ['APPLICATION_VERSION'])
    print('request: {}'.format(json.dumps(event)))

    bucket_name = os.environ['TEMP_BUCKET_NAME']
    print("bucket_name: " + os.environ['TEMP_BUCKET_NAME'])

    appfabric_bucket_name = os.environ['APPFABRIC_BUCKET_NAME']
    print("appfabric_bucket_name: " + os.environ['APPFABRIC_BUCKET_NAME'])

    appfabric_firehose_arn = os.environ['APPFABRIC_FIREHOSE_ARN']
    print("appfabric_firehose_arn: " + os.environ['APPFABRIC_FIREHOSE_ARN'])

    target_directory = '/tmp/'  # The local 'tmp' directory in the Lambda function

    # Remove the /tmp/ directory after processing
    remove_tmp_directory()

    download_templates_from_s3(bucket_name, target_directory + '/Templates')
    
    formatted_date = datetime.datetime.now().strftime("%Y-%m-%d")
    copy_directories(os.path.join(target_directory, 'Templates'), os.path.join(target_directory, formatted_date))
    
    # Call the function to start traversing directories
    traverse_directories(os.path.join(target_directory, formatted_date), appfabric_bucket_name, appfabric_firehose_arn)
    
    tarball_path = create_tmp_tarball(formatted_date)
    print(f"path to tar file is {tarball_path}")
    
    # Upload the tar file to S3
    s3.upload_file(tarball_path, bucket_name, f"{formatted_date}.tar.gz")

    expiration_time_in_seconds = 86400  # 1 day
    signed_url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': f"{formatted_date}.tar.gz"},
        ExpiresIn=expiration_time_in_seconds
    )
    print(f"generated presigned url is {signed_url}")

    # Remove the /tmp/ directory after processing
    remove_tmp_directory()
    
    return {
        'statusCode': 200, 
        'headers': {
            'Content-Type': 'text/html'
        },
        'body': signed_url
    }
    
    
    