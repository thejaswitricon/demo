import csv
import requests
import json
import subprocess
import os

# Script 1: Fetching Monitors and Updating CSV

MONITORS_API_ENDPOINT = "https://synthetics.newrelic.com/synthetics/api/v3/monitors"
PAGE_SIZE = 100  # Number of monitors to retrieve per page

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

            # Break the loop if the retrieved monitors are less than the page size
            if len(monitors_data) < PAGE_SIZE:
                break

            offset += PAGE_SIZE
        else:
            print(f"Failed to retrieve {monitor_type} monitors")
            break

    return monitors

# Load CSV data and prepare a list of service names
service_names = []

with open("data-source.csv", mode="r") as csv_file:
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
                # Assuming the monitor name format is "${serviceName} #..."
                parts = monitor["name"].split()
                if len(parts) > 1:
                    service_hash = parts[-1]
                    # Assuming pingMonitorId is a valid key in your CSV
                    if service_hash.startswith("#"):
                        with open("data-source.csv", mode="r") as csv_file:
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
                        with open("data-source.csv", mode="w", newline="") as csv_file:
                            fieldnames = data[0].keys()
                            csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                            csv_writer.writeheader()
                            csv_writer.writerows(data)
                        break
