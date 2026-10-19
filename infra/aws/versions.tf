terraform {
  required_version = ">= 1.5.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  # On every resource, so anything left behind is easy to find.
  default_tags {
    tags = {
      Project   = "chapter-and-verse"
      ManagedBy = "terraform"
    }
  }
}
