variable "region" {
  type    = string
  default = "eu-west-2"
}

variable "name" {
  type    = string
  default = "chapter-and-verse"
}

variable "admin_cidr" {
  description = "Your public IP as a /32. Only this address can reach the Kubernetes API."
  type        = string
}

variable "gpu_nodes" {
  description = "GPU nodes to start with. The node group ignores later changes, so set it when you create the cluster."
  type        = number
  default     = 0
}
