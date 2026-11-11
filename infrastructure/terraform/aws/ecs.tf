locals {
  demo_services = var.enable_demo_services ? {
    "api-gateway"          = { downstream = "http://user-service.${var.name}.local:8080,http://payment-service.${var.name}.local:8080" }
    "user-service"         = { downstream = "" }
    "payment-service"      = { downstream = "http://notification-service.${var.name}.local:8080" }
    "notification-service" = { downstream = "" }
  } : {}
  ecr = { for r in ["backend", "frontend", "demo-service"] : r => aws_ecr_repository.repo[r].repository_url }
}

resource "aws_ecr_repository" "repo" {
  for_each             = toset(["backend", "frontend", "demo-service"])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_lifecycle_policy" "repo" {
  for_each   = aws_ecr_repository.repo
  repository = each.value.name
  policy     = jsonencode({ rules = [{ rulePriority = 1, description = "keep last 20", selection = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }, action = { type = "expire" } }] })
}

resource "aws_cloudwatch_log_group" "svc" {
  for_each          = toset(concat(["backend", "frontend"], keys(local.demo_services)))
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = 7
}

resource "aws_ecs_cluster" "main" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "disabled" # cost; ECS service metrics in CloudWatch are free
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "${var.name}.local"
  vpc  = aws_vpc.main.id
}

# ---------------------------------------------------------------- backend
resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.name}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.backend.arn
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }
  container_definitions = jsonencode([{
    name                   = "backend"
    image                  = "${local.ecr.backend}:${var.image_tag}"
    essential              = true
    portMappings           = [{ containerPort = 8000 }]
    readonlyRootFilesystem = true
    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "CLOUD_PROVIDER", value = "aws" },
      { name = "AWS_REGION", value = var.region },
      { name = "AWS_ECS_CLUSTER", value = var.name },
      { name = "AWS_SERVICE_MAP", value = join(",", [for k, _ in local.demo_services : "${k}=${var.name}-${k}"]) },
      { name = "AWS_RDS_INSTANCE_ID", value = aws_db_instance.main.identifier },
      { name = "AWS_LOG_GROUP_PREFIX", value = "/ecs/${var.name}" },
      { name = "TICK_SECONDS", value = "60" },
      { name = "CORS_ORIGINS", value = "http://${aws_lb.main.dns_name}" },
    ]
    secrets = [
      { name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.app.arn}:DATABASE_URL::" },
      { name = "JWT_SECRET", valueFrom = "${aws_secretsmanager_secret.app.arn}:JWT_SECRET::" },
    ]
    mountPoints      = [{ sourceVolume = "tmp", containerPath = "/tmp" }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.svc["backend"].name, awslogs-region = var.region, awslogs-stream-prefix = "backend" } }
  }])
  volume { name = "tmp" }
}

resource "aws_ecs_service" "backend" {
  name            = "${var.name}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1 # singleton control loop (see ADR-009)
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

# --------------------------------------------------------------- frontend
resource "aws_ecs_task_definition" "frontend" {
  family                   = "${var.name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }
  container_definitions = jsonencode([{
    name             = "frontend"
    image            = "${local.ecr.frontend}:${var.image_tag}"
    essential        = true
    portMappings     = [{ containerPort = 8080 }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.svc["frontend"].name, awslogs-region = var.region, awslogs-stream-prefix = "frontend" } }
  }])
}

resource "aws_ecs_service" "frontend" {
  name            = "${var.name}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = 1
  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 8080
  }
}

# ---------------------------------------------------------- demo services
resource "aws_service_discovery_service" "demo" {
  for_each = local.demo_services
  name     = each.key
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}

resource "aws_ecs_task_definition" "demo" {
  for_each                 = local.demo_services
  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.demo.arn
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }
  container_definitions = jsonencode([{
    name             = "app"
    image            = "${local.ecr["demo-service"]}:${var.image_tag}"
    essential        = true
    portMappings     = [{ containerPort = 8080 }]
    environment      = [{ name = "SERVICE_NAME", value = each.key }, { name = "DOWNSTREAM", value = each.value.downstream }]
    healthCheck      = { command = ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/ready')\""], interval = 15, retries = 3, timeout = 5 }
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.svc[each.key].name, awslogs-region = var.region, awslogs-stream-prefix = each.key } }
  }])
}

resource "aws_ecs_service" "demo" {
  for_each        = local.demo_services
  name            = "${var.name}-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.demo[each.key].arn
  desired_count   = 1
  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
  service_registries { registry_arn = aws_service_discovery_service.demo[each.key].arn }
  dynamic "load_balancer" {
    for_each = each.key == "api-gateway" ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.gateway.arn
      container_name   = "app"
      container_port   = 8080
    }
  }
  # CloudOps AI itself changes desired_count/task definition during remediation.
  lifecycle { ignore_changes = [desired_count, task_definition] }
}
