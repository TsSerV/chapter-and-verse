output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name} --alias eks-${module.eks.cluster_name}"
}

output "karpenter_queue" {
  value = module.karpenter.queue_name
}
