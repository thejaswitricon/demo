import csv
import requests
import subprocess
import os
import time
import json
import shutil

# Script 1: Fetching Monitors and Updating CSV

MONITORS_API_ENDPOINT = "https://synthetics.newrelic.com/synthetics/api/v3/monitors"
PAGE_SIZE = 100  # Number of monitors to retrieve per page
CSV_FILE_SOURCE = "data-source.csv"
destination_file = "data.csv"
shutil.copy(CSV_FILE_SOURCE, destination_file)

APPLICATIONS_API_ENDPOINT = "https://api.newrelic.com/v2/applications.json"

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

        response = requests.get(MONITORS_API_ENDPOINT, headers=headers, params=params)
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

with open("data.csv", mode="r") as csv_file:
    csv_reader = csv.DictReader(csv_file)
    for row in csv_reader:
        if row["type"] == "service":
            service_names.append(row["serviceName"])

# Fetch monitors and update CSV file with monitor IDs
for monitor_type in ["SIMPLE", "CERT_CHECK", "SCRIPT_API", "SCRIPT_BROWSER", "BROWSER"]:
    monitors = fetch_monitors_by_type(monitor_type)
    for monitor in monitors:
        for service_name in service_names:
            if monitor["name"].startswith(service_name):
                parts = monitor["name"].split()
                if len(parts) > 1:
                    service_hash = parts[-1]
                    if service_hash.startswith("#"):
                        with open("data.csv", mode="r") as csv_file:
                            csv_reader = csv.DictReader(csv_file)
                            data = list(csv_reader)
                            for row in data:
                                if row["serviceName"] == service_name:
                                    if row["type"] != "product":
                                        if "#health" in parts and "#ping" in parts and "#critical" in parts:
                                            row["healthMonitorId"] = monitor["id"]
                                        elif "#ping" in parts and "#critical" in parts:
                                            row["pingMonitorId"] = monitor["id"]
                                    elif "#script" in parts and "#critical" in parts:
                                        row["scriptMonitorId"] = monitor["id"]
                        with open("data.csv", mode="w", newline="") as csv_file:
                            fieldnames = data[0].keys()
                            csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                            csv_writer.writeheader()
                            csv_writer.writerows(data)
                        break

# Script 2: Updating Entity GUIDs

def fetch_application_names(filter_name, offset):
    params = {
        "filter[name]": filter_name,
        "offset": offset,
        "limit": PAGE_SIZE
    }

    response = requests.get(APPLICATIONS_API_ENDPOINT, headers=headers, params=params)

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
                updated_row['apmEntityGuid'] = updated_guid
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
                tf_file.write(tf_config)
                tf_file.write('\n')
                print(f"Terraform configuration added for: {service_name}")

        print("Terraform configurations written to data.tf")

        subprocess.run(['terraform', 'init', '-input=false', '-backend=false'], check=True)
        subprocess.run(['terraform', 'apply', '-auto-approve', '-input=false'], check=True)

        time.sleep(5)

        entity_guids = {}
        try:
            with open('terraform.tfstate', 'r') as state_file:
                state_data = json.load(state_file)
                resources = state_data.get("resources", [])
                for resource in resources:
                    if resource.get("type") == "newrelic_entity":
                        service_name = resource.get("instances", [{}])[0].get("attributes", {}).get("name")
                        guid = resource.get("instances", [{}])[0].get("attributes", {}).get("guid")
                        if service_name and guid:
                            entity_guids[service_name] = guid
        except Exception as e:
            print("Error reading terraform.tfstate:", e)

        for service_name, guid in entity_guids.items():
            matching_application_guids[service_name] = guid
            print(f"Service Name: {service_name}, Entity GUID: {guid}")

        update_entity_guids_csv(matching_application_guids)
        print("Updated data.csv with entity GUIDs")

        if os.path.exists('terraform.tfstate'):
            os.remove('terraform.tfstate')

        if os.path.exists('terraform.tfstate.backup'):
            os.remove('terraform.tfstate.backup')

        if os.path.exists('data.tf'):
            os.remove('data.tf')

        if os.path.exists('.terraform.lock.hcl'):
            os.remove('.terraform.lock.hcl')

        if os.path.exists('.terraform'):
            os.remove('.terraform')


    else:
        print("No matching application names found")
