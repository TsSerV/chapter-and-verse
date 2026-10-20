data "aws_availability_zones" "available" {
  state = "available"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = var.name
  cidr = "10.0.0.0/16"
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)

  # Public subnets only. A NAT gateway charges for every GB of images and model weights.
  public_subnets          = ["10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/20"]
  map_public_ip_on_launch = true
  enable_nat_gateway      = false
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.29.0"

  name               = var.name
  kubernetes_version = "1.37"

  endpoint_public_access                   = true
  endpoint_public_access_cidrs             = [var.admin_cidr]
  enable_cluster_creator_admin_permissions = true

  # The cluster lives for one session. A KMS key would wait 30 days for deletion after each one.
  encryption_config           = null
  enabled_log_types           = []
  create_cloudwatch_log_group = false

  addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni = {
      before_compute = true
    }
    eks-pod-identity-agent = {
      before_compute = true
    }
  }

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = ["t4g.medium"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
    }

    gpu = {
      # The NVIDIA AMI has the driver. The device plugin is installed separately.
      ami_type = "AL2023_x86_64_NVIDIA"
      # Two sizes with the same L4 GPU. When one is out of capacity, the other can launch.
      instance_types = ["g6.xlarge", "g6.2xlarge"]
      capacity_type  = "SPOT"
      min_size       = 0
      max_size       = 1
      desired_size   = var.gpu_nodes

      # Room for the vLLM image and model weights.
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 100
            volume_type           = "gp3"
            delete_on_termination = true
          }
        }
      }

      # Only pods that tolerate this run on the GPU node.
      taints = {
        gpu = {
          key    = "nvidia.com/gpu"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      }
    }
  }
}
