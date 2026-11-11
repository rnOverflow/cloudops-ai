output "url" {
  value = "http://${aws_lb.main.dns_name}"
}

output "ecr_repositories" {
  value = local.ecr
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "rds_endpoint" {
  value     = aws_db_instance.main.address
  sensitive = true
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}
