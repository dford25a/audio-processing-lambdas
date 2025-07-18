# ECR Repositories for container images
resource "aws_ecr_repository" "segment_audio" {
  name                 = "segment-audio"
  image_tag_mutability = "MUTABLE"
  
  # Added lifecycle block to handle existing repository
  lifecycle {
    prevent_destroy = true
    ignore_changes = [name]
  }
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  tags = {
    Environment = var.environment
  }
}

resource "aws_ecr_repository" "faster_whisper" {
  name                 = "faster-whisper"
  image_tag_mutability = "MUTABLE"
  
  # Added lifecycle block to handle existing repository
  lifecycle {
    prevent_destroy = true
    ignore_changes = [name]
  }
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  tags = {
    Environment = var.environment
  }
}