terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Remote state (recommended): uncomment and create the bucket/table first.
  # backend "s3" {
  #   bucket         = "<your-tf-state-bucket>"
  #   key            = "cloudops-ai/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "<your-tf-lock-table>"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "cloudops-ai", Environment = var.environment, ManagedBy = "terraform" }
  }
}
