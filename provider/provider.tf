terraform {
  required_version = ">= 1.0.0"
  required_providers {
    external = {
      source  = "hashicorp/external"
      version = ">= 1.0.0"
    }
    newrelic = {
      source  = "newrelic/newrelic"
      version = ">= 3.25.0"
    }
  }
}