data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role: pull images, write logs, read the app secret.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "read-app-secret"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.app.arn] }]
  })
}

# Task role for the CloudOps backend: exactly the APIs the AWSProvider uses, scoped to this cluster.
resource "aws_iam_role" "backend" {
  name               = "${var.name}-backend"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "backend" {
  name = "cloudops-provider"
  role = aws_iam_role.backend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "ObserveAndRemediateEcs"
        Effect    = "Allow"
        Action    = ["ecs:DescribeServices", "ecs:UpdateService", "ecs:ListTasks", "ecs:DescribeTasks", "ecs:StopTask"]
        Resource  = "*"
        Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.main.arn } }
      },
      {
        Sid      = "TaskDefinitionsForRollbackAndDeploy"
        Effect   = "Allow"
        Action   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition", "ecs:DescribeClusters"]
        Resource = "*"
      },
      {
        Sid      = "PassOnlyCloudOpsRoles"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.execution.arn, aws_iam_role.demo.arn]
      },
      {
        Sid      = "ReadMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics"]
        Resource = "*"
      },
      {
        Sid      = "ReadLogs"
        Effect   = "Allow"
        Action   = ["logs:FilterLogEvents", "logs:DescribeLogGroups"]
        Resource = "arn:aws:logs:${var.region}:*:log-group:/ecs/${var.name}*"
      },
      {
        Sid      = "AuditExports"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.artifacts.arn}/audit-exports/*"
      },
    ]
  })
}

# Demo services need no AWS permissions.
resource "aws_iam_role" "demo" {
  name               = "${var.name}-demo-service"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
