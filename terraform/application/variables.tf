variable "environment" {
  description = "Deployment environment (prod or dev)"
  type        = string
}

variable "openai_api_key" {
  description = "OpenAI API key"
  type        = string
  sensitive   = true
}

variable "appsync_api_url" {
  description = "The GraphQL endpoint URL of your AppSync API."
  type        = string
  # This will be populated from your dev.tfvars or prod.tfvars
}

variable "appsync_api_id" {
  description = "The ID of your AppSync GraphQL API (e.g., from the AppSync console or CloudFormation output)."
  type        = string
  # This needs to be added to your .tfvars files
}

variable "appsync_api_key" {
  description = "The API key for the AppSync API."
  type        = string
  sensitive   = true # Mark as sensitive to avoid showing in CLI output
}

locals {
  # Environment-specific configuration
  env_config = {
    prod = {
      s3_bucket       = "scribe8a8fcf3f6cb14734bce4bd48352f8043195641-dev" # Note: Your prod S3 bucket seems to have '-dev' in its name
      dynamodb_table  = "Session-ejphalvgizhdjbbzuj2vahx7ii-dev" # Note: Your prod DynamoDB table seems to have '-dev' in its name
      function_suffix = "-prod"
    },
    dev = {
      s3_bucket       = "scribe8a8fcf3f6cb14734bce4bd48352f8043acdd4-devsort"  
      dynamodb_table  = "Session-ebn6wlprprdnvdmndj7wh7ddja-devsort"
      function_suffix = "-dev"
    }
  }

  # Get config for the current environment
  config = local.env_config[var.environment]
}
