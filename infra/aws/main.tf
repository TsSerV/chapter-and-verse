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

  # Karpenter launches nodes into the subnets with this tag.
  public_subnet_tags = {
    "karpenter.sh/discovery" = var.name
  }
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

  # Karpenter gives its nodes the security group with this tag, the one every node shares.
  node_security_group_tags = {
    "karpenter.sh/discovery" = var.name
  }

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = ["t4g.medium"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
    }
  }
}

# IAM roles for the Karpenter controller and its nodes, and the queue that warns of spot
# interruptions. The GPU nodes themselves come from the NodePool in deploy/aws/karpenter.yaml.
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "21.29.0"

  cluster_name = module.eks.cluster_name

  # A fixed name, because the EC2NodeClass refers to it.
  node_iam_role_use_name_prefix = false
  node_iam_role_name            = "${var.name}-karpenter-node"
}
