variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "demo"
}

variable "name" {
  type    = string
  default = "cloudops"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "image_tag" {
  description = "Container image tag pushed to ECR by CI"
  type        = string
  default     = "latest"
}

variable "allowed_ingress_cidrs" {
  description = "CIDRs allowed to reach the ALB. Restrict to your IP for a private demo."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "acm_certificate_arn" {
  description = "Optional ACM certificate for HTTPS. Without it the ALB serves HTTP only (demo)."
  type        = string
  default     = ""
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "enable_demo_services" {
  description = "Run the four demo microservices on Fargate Spot"
  type        = bool
  default     = true
}

variable "monthly_budget_usd" {
  description = "Create an AWS Budget alert at this monthly amount (0 disables)"
  type        = number
  default     = 50
}

variable "budget_alert_email" {
  type    = string
  default = ""
}
