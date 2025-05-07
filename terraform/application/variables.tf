variable "environment" {
  description = "Deployment environment (prod or dev)"
  type        = string
}

variable "openai_api_key" {
  description = "OpenAI API key"
  type        = string
  sensitive   = true
}

locals {
  # Environment-specific configuration
  env_config = {
    prod = {
      s3_bucket       = "scribe8a8fcf3f6cb14734bce4bd48352f8043195641-dev"
      dynamodb_table  = "Session-ejphalvgizhdjbbzuj2vahx7ii-dev"
      function_suffix = "-prod"  # No suffix for prod
    },
    dev = {
      s3_bucket       = "scribe8a8fcf3f6cb14734bce4bd48352f80433dbd8-devsort"  
      dynamodb_table  = "Session-a6imejpsvbd67dd44nsarzri2m-devsort"
      function_suffix = "-dev"  # Add -dev suffix to function names
    }
  }

  # Get config for the current environment
  config = local.env_config[var.environment]
}
