import csv
import os
import requests
import subprocess
import time
import shutil

# Define the base directory where you want to search for subdirectories
base_directory = "../dashboards/dynamic"

# Path to the data.csv file that contains folder names
data_csv_file = os.path.join(base_directory, "data.csv")

# Check if the data.csv file exists
if os.path.exists(data_csv_file):
    # Read the folder names from data.csv
    folder_names = []
    with open(data_csv_file, mode="r") as csv_file:
        csv_reader = csv.DictReader(csv_file)
        for row in csv_reader:
            folder_name = row.get("filename")  # Adjust the column name as needed
            if folder_name:
                folder_names.append(folder_name)

    # Loop through each folder name and run your script for each folder
    for folder_name in folder_names:
        # Construct the paths for CSV files within the current folder
        CSV_FILE_SOURCE = os.path.join(base_directory, folder_name, "data-source.csv")
        destination_file = os.path.join(base_directory, folder_name, "data.csv")
        provider_tf_path = "../provider/provider.tf"
        data_tf_path = "data.tf"
        MONITORS_API_ENDPOINT = "https://synthetics.newrelic.com/synthetics/api/v3/monitors"
        PAGE_SIZE = 100  # Number of monitors to retrieve per page
        shutil.copy(CSV_FILE_SOURCE, destination_file)

        APPLICATIONS_API_ENDPOINT = "https://api.newrelic.com/v2/applications.json"

        print(f"Processing CSV files in folder: {folder_name}")
        print(f"CSV_FILE_SOURCE: {CSV_FILE_SOURCE}")
        print(f"destination_file: {destination_file} \n")

        headers = {
            "Api-Key": os.environ.get("NEW_RELIC_API_KEY")
        }

        if headers["Api-Key"] is None:
            print("API_KEY environment variable is not set.")
            exit(1)

        def fetch_monitors_by_type(monitor_type):
            offset = 0
            limit = PAGE_SIZE
            monitors = []

            while True:
                params = {
                    "offset": offset,
                    "limit": limit
                }

                response = requests.get(MONITORS_API_ENDPOINT, headers=headers, params=params, timeout=20)
                if response.status_code == 200:
                    monitors_data = response.json().get("monitors")
                    monitors.extend([monitor for monitor in monitors_data if monitor.get("type") == monitor_type])

                    if len(monitors_data) < PAGE_SIZE:
                        break

                    offset += PAGE_SIZE
                else:
                    print(f"Failed to retrieve {monitor_type} monitors")
                    break

            return monitors

        # Load CSV data and prepare a list of service names
        service_names = []

        with open(destination_file, mode="r") as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for row in csv_reader:
                if row["rowType"] == "service":
                    service_names.append(row["serviceName"])

        # Fetch monitors and update CSV file with monitor IDs
        # for monitor_type in ["SIMPLE", "CERT_CHECK", "SCRIPT_API", "SCRIPT_BROWSER", "BROWSER"]:
        #     monitors = fetch_monitors_by_type(monitor_type)
        #     for monitor in monitors:
        #         for service_name in service_names:
        #             if monitor["name"].startswith(service_name):
        #                 parts = monitor["name"].split()
        #                 if len(parts) > 1:
        #                     service_hash = parts[-1]
        #                     if service_hash.startswith("#"):
        #                         with open(destination_file, mode="r") as csv_file:
        #                             csv_reader = csv.DictReader(csv_file)
        #                             data = list(csv_reader)
        #                             for row in data:
        #                                 if row["serviceName"] == service_name:
        #                                     if row["rowType"] != "product":
        #                                         if "#health" in parts and "#ping" in parts and "#critical" in parts:
        #                                             row["healthMonitorId"] = monitor["id"]
        #                                         elif "#ping" in parts and "#critical" in parts:
        #                                             row["pingMonitorId"] = monitor["id"]
        #                                     elif "#script" in parts and "#critical" in parts:
        #                                         row["scriptMonitorId"] = monitor["id"]
        #                         with open(destination_file, mode="w", newline="") as csv_file:
        #                             fieldnames = data[0].keys()
        #                             csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        #                             csv_writer.writeheader()
        #                             csv_writer.writerows(data)
        #                         break

        # Script 2: Updating Entity GUIDs

        def fetch_application_names(filter_name, offset):
            params = {
                "filter[name]": filter_name,
                "offset": offset,
                "limit": PAGE_SIZE
            }

            response = requests.get(APPLICATIONS_API_ENDPOINT, headers=headers, params=params, timeout=20)

            if response.status_code == 200:
                applications_data = response.json().get("applications")
                return applications_data
            else:
                print(f"Failed to retrieve application names for filter: {filter_name}")
                return []

        def update_entity_guids_csv(guids_dict):
            updated_rows = []
            with open(destination_file, 'r') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    service_name = row.get('serviceName', '')
                    updated_row = row.copy()
                    if service_name in guids_dict:
                        updated_guid = guids_dict[service_name]
                        updated_row['apmEntityGuid'] = updated_guid if row["rowType"] == "service" else ""
                    updated_rows.append(updated_row)

            with open(destination_file, 'w', newline='') as csvfile:
                fieldnames = updated_rows[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(updated_rows)

        if __name__ == "__main__":
            matching_application_guids = {}

            with open(destination_file, mode="r") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    service_name = row.get("serviceName")
                    if service_name:
                        offset = 0
                        while True:
                            applications_data = fetch_application_names(service_name, offset)
                            if not applications_data:
                                break

                            for app_data in applications_data:
                                app_name = app_data.get("name")
                                matching_application_guids[app_name] = None
                                print(f"Matching application found: {app_name}")

                            if len(applications_data) < PAGE_SIZE:
                                break

                            offset += PAGE_SIZE

            if matching_application_guids:
                with open("data.tf", "w") as tf_file:
                    tf_file.write('''
        # Terraform data blocks
        ''')
                    for idx, service_name in enumerate(matching_application_guids, start=1):
                        tf_config = f'''
        data "newrelic_entity" "app_{idx}" {{
        name = "{service_name}"
        domain = "APM"
        }}
        '''
                        tf_output_config = f'''
        output "{service_name}" {{
      value = {{
        guid           = data.newrelic_entity.app_{idx}.guid
        application_id = data.newrelic_entity.app_{idx}.application_id
      }}
    }}
    '''
                        tf_file.write(tf_config)
                        tf_file.write('\n')
                        tf_file.write(tf_output_config)  # Adding output configuration
                        tf_file.write('\n')
                        print(f"Terraform configuration and output added for: {service_name}")

                # Read the content of provider.tf and data.tf
                with open(provider_tf_path, "r") as provider_file, open(data_tf_path, "r") as data_file:
                    provider_content = provider_file.read()
                    data_content = data_file.read()

                # Concatenate the content of provider.tf and data.tf with provider.tf content first
                combined_content = provider_content + data_content

                # Write the combined content back to data.tf
                with open(data_tf_path, "w") as data_file:
                    data_file.write(combined_content)
        
                print("Terraform configurations written to data.tf")
                
                # Run terraform fmt to format the configuration file
                subprocess.run(['terraform', 'fmt'], check=True)  # nosec
                print("Terraform format check complete.")

                # Run terraform validate to check the configuration's validity
                validate_process = subprocess.run(['terraform', 'validate'], capture_output=True, text=True)  # nosec  
                if validate_process.returncode == 0:
                    print("Terraform validation successful.")
                else:
                    print("Terraform validation failed:")
                    print(validate_process.stdout)
                    print(validate_process.stderr)

                subprocess.run(['terraform', 'init', '-input=false', '-backend=false'], check=True)  # nosec

                time.sleep(5)
                apply_process = subprocess.run(['terraform', 'apply', '-auto-approve', '-input=false'], capture_output=True, text=True, shell=True)  # nosec
                if apply_process.returncode == 0:
                    apply_output = apply_process.stdout

                    # Extract GUIDs from the apply_output using string manipulation or regex
                    tf_outputs = {}  # Create an empty dictionary to store extracted GUIDs
                    output_lines = apply_output.split("\n")
                    for line in output_lines:
                        if "=" in line:
                            parts = line.split("=")
                            service_name = parts[0].strip()
                            guid = parts[1].strip().replace('"', '')
                            tf_outputs[service_name] = guid
                            print(f"Extracted GUID for {service_name}: {guid}")

                # Update the CSV based on the tf_outputs dictionary
                update_entity_guids_csv(tf_outputs)
                print("CSV updated with GUIDs.")

                if os.path.exists('terraform.tfstate'):
                    os.remove('terraform.tfstate')

                if os.path.exists('terraform.tfstate.backup'):
                    os.remove('terraform.tfstate.backup')

                # if os.path.exists('data.tf'):
                #     os.remove('data.tf')

            else:
                print("No matching application names found")


else:
    print("data.csv file not found in the dynamic folder")