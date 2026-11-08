# Serving models on a GPU in AWS

How to create a temporary EKS cluster, serve an open model on an NVIDIA L4 GPU, and
destroy the cluster at the end.

## On AWS, with a GPU

This serves an open model on an NVIDIA L4 GPU with [vLLM](https://docs.vllm.ai/) behind
[KServe](https://kserve.github.io/website/), through an OpenAI compatible API. The
service does not use it yet: `/ask` still calls Claude.

Terraform in `infra/aws/` creates an EKS cluster in eu-west-2 (London) with one ARM
`t4g.medium` node for the system pods. GPU nodes come from Karpenter: it starts an NVIDIA
L4 node when a model needs one, and removes the node once it is empty. Only pods that
tolerate the GPU nodes' taint run there. The cluster is built to be destroyed after each
session, and nothing in it keeps data.

There is no NAT gateway, because it charges by the hour and for every GB of image and
weights. The nodes are in public subnets instead, and their security group blocks inbound
traffic from the internet. The Kubernetes API accepts one IP address only.

### What it costs

London prices in US dollars, checked in October 2026. Spot prices change.

| Part | Per hour |
| --- | --- |
| EKS control plane | $0.10 |
| GPU node, `g6.xlarge` on spot | $0.35 to $0.41 |
| GPU node, `g6.xlarge` on demand | $1.02 |
| System node, `t4g.medium` | $0.04 |

Karpenter starts a spot node when London has capacity, and an on-demand node when it has
none. With one GPU node the cluster costs $0.49 to $0.55 an hour on spot and $1.16 on
demand, plus a few cents for disks and public IP addresses.

**Run `terraform destroy` at the end of every session.** Left running, the cluster costs
about $3.40 a day with no GPU node, and $12 to $28 a day with one.

### What you need

- An AWS account where you can create IAM roles, a VPC and an EKS cluster.
- Quota for G instances in eu-west-2. New accounts start at 0. In Service Quotas,
  [request](https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html)
  8 vCPUs for "All G and VT Spot Instance Requests" and 8 for "Running On-Demand G and VT
  instances": room for two `g6.xlarge` nodes either way. Approval can take a day or two.
- The [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html),
  signed in to that account. `aws sts get-caller-identity` shows which account it uses.
- [Terraform 1.16](https://developer.hashicorp.com/terraform/install), and kubectl and
  Helm 4 as for [kind](kubernetes.md).

### Create it

Run every command from the repository root. `admin_cidr` is your current public IP
address, the only one the Kubernetes API will accept:

```sh
export TF_VAR_admin_cidr="$(curl -s https://checkip.amazonaws.com)/32"
terraform -chdir=infra/aws init
terraform -chdir=infra/aws apply
```

The apply takes about 12 minutes. Keep `TF_VAR_admin_cidr` set in this terminal:
`destroy` needs it too. If your IP address changes, kubectl times out. Export
`TF_VAR_admin_cidr` again and run the same apply.

Point kubectl at the cluster, then install the NVIDIA device plugin. The node's AMI brings
the NVIDIA driver, and the plugin makes the GPU visible to Kubernetes as `nvidia.com/gpu`:

```sh
eval "$(terraform -chdir=infra/aws output -raw kubeconfig_command)"
helm install nvdp nvidia-device-plugin --repo https://nvidia.github.io/k8s-device-plugin \
  --version 0.20.1 --namespace nvidia --create-namespace
```

Install Karpenter on the system node, and give it the NodePool. One replica, because the
chart's default is two on different nodes, and the cluster has one system node.

```sh
helm install karpenter oci://public.ecr.aws/karpenter/karpenter --version 1.15.1 \
  --namespace kube-system \
  --set settings.clusterName=chapter-and-verse \
  --set settings.interruptionQueue="$(terraform -chdir=infra/aws output -raw karpenter_queue)" \
  --set replicas=1 \
  --wait
kubectl apply -f deploy/aws/karpenter.yaml
```

Check that a pod can use the GPU. This Job runs `nvidia-smi` once. No GPU node runs yet.
Karpenter starts one for this Job, and removes it a minute after the Job is deleted.

```sh
kubectl apply -f deploy/aws/gpu-check.yaml
kubectl wait --for=condition=complete job/gpu-check --timeout=10m
kubectl logs job/gpu-check
kubectl delete job gpu-check
```

The log shows an NVIDIA L4 with 23,034 MiB of memory.

### Serve a model

Install Prometheus and KEDA first. KEDA scales the model on vLLM's metrics, which
Prometheus collects. KServe looks for KEDA only when it starts, so KEDA goes in before
KServe.

```sh
helm install prometheus prometheus --repo https://prometheus-community.github.io/helm-charts \
  --version 29.37.0 --namespace monitoring --create-namespace \
  --set alertmanager.enabled=false \
  --set kube-state-metrics.enabled=false \
  --set prometheus-node-exporter.enabled=false \
  --set prometheus-pushgateway.enabled=false \
  --set server.persistentVolume.enabled=false \
  --set server.global.scrape_interval=15s \
  --wait
helm install keda keda --repo https://kedacore.github.io/charts --version 2.21.0 \
  --namespace keda --create-namespace --wait
```

KServe runs the model, and the registry says which one. Install cert-manager before
KServe, because KServe's webhooks need certificates. Then install KServe in Standard
mode: a plain Deployment and Service per model, with no Knative and no Istio. You reach
the model with `port-forward`, so KServe creates no Ingress.

```sh
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager --version v1.21.3 \
  --namespace cert-manager --create-namespace --set crds.enabled=true --wait
helm install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd --version v0.21.0 \
  --namespace kserve --create-namespace --wait
helm install kserve oci://ghcr.io/kserve/charts/kserve-resources --version v0.21.0 \
  --namespace kserve \
  --set kserve.controller.deploymentMode=Standard \
  --set kserve.controller.gateway.disableIngressCreation=true \
  --set kserve.controller.gateway.disableIstioVirtualHost=true \
  --wait
```

Both run on the system node. The GPU node's taint keeps them off the GPU.

With [MLflow running](model-registry.md), render the manifests for the `champion` alias
and apply them:

```sh
kubectl create namespace models
uv run python -m serving.render | kubectl apply -n models -f -
kubectl wait --for=condition=Ready inferenceservice/answerer -n models --timeout=20m
```

`serving/render.py` prints two manifests. The ServingRuntime says how to run vLLM: the
image, the probes and the volumes. The InferenceService says what to run: the commit and
the flags of the version, and one GPU. Its `app.kubernetes.io/version` label is the
version number, so a running pod leads back to its exact weights and its measured
numbers. `--alias` and `--target` choose another alias or cluster. The defaults are
`champion` and `eks`.

A version registered with `--max-num-seqs` runs one or two replicas. KEDA counts the
requests inside vLLM, running or waiting, and adds a replica when they average more than
three quarters of the batch: 12 for a batch of 16. Waiting requests alone would drop to
zero as soon as the second replica took load, and it would be removed again. The second
replica stops 5 minutes after the load drops. Prometheus scrapes each pod twice, through
the pod and through the Service, because KServe copies the scrape annotations to both, so
the query counts the pod's own scrape only.

vLLM downloads the weights itself, not KServe's storage initializer. The initializer held
most of the model in memory while it downloaded, 2.6 GiB for Qwen3-1.7B. Its memory grows
with the model, and the GPU node has 16 GiB for everything.

With version 2, Qwen3-1.7B, the first start takes about 8 minutes, more than half of it
the image pull. To serve another version, move the alias and apply again:

```sh
uv run python -m serving.registry alias champion 4
uv run python -m serving.render | kubectl apply -n models -f -
```

After a change, wait with `kubectl rollout status deployment/answerer-predictor -n models`.
`kubectl wait` on the InferenceService can miss it, because KServe copies
`observedGeneration` from the Deployment
([kserve/kserve#6081](https://github.com/kserve/kserve/issues/6081)).

There is one GPU, so the old pod stops before the new one starts. Nothing answers until
the new pod is Ready.

To reach the model, keep this running in its own terminal:

```sh
kubectl port-forward -n models svc/answerer-predictor 8080:80
```

Then send a chat request. `model` is always `answerer`, whatever version is behind it:

```sh
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "answerer",
       "messages": [{"role": "user", "content": "In one sentence, what does the Equality Act 2010 do?"}],
       "max_tokens": 300,
       "chat_template_kwargs": {"enable_thinking": false}}'
```

The answer is in `choices[0].message.content`. `enable_thinking: false` skips Qwen3's
thinking step, so the answer comes back sooner. vLLM's Prometheus metrics are at
http://127.0.0.1:8080/metrics.

The same works on [kind](kubernetes.md), without a GPU. Install Prometheus, KEDA,
cert-manager and KServe with the same commands, then render the `local` alias for kind:

```sh
kubectl create namespace models
uv run python -m serving.render --alias local --target kind | kubectl apply -n models -f -
```

This uses vLLM's CPU build, with no compile step and a small KV cache, so it fits in
about 5 GiB. An answer takes about 15 seconds. kind has room for one replica, so a second
one waits as Pending.

### Destroy it

```sh
kubectl delete inferenceservice --all -n models
kubectl delete nodepool gpu
kubectl get nodeclaims
```

Run the last line until it says `No resources found`. Then:

```sh
kubectl delete ec2nodeclass gpu
terraform -chdir=infra/aws destroy
kubectl config delete-context eks-chapter-and-verse
```

Karpenter's nodes are not in Terraform's state. Deleting the NodePool makes Karpenter stop
them, and deleting the EC2NodeClass makes it delete the instance profile it created. Skip
these and a GPU node keeps running, and the destroy cannot delete the node role or the
VPC.

The destroy takes about 11 minutes. Then check that the region has no cluster, instance,
disk or instance profile left. In an account used only for this, each command prints an
empty list:

```sh
aws eks list-clusters --region eu-west-2 --query clusters
aws ec2 describe-instances --region eu-west-2 \
  --filters Name=instance-state-name,Values=pending,running,stopping \
  --query 'Reservations[].Instances[].InstanceId'
aws ec2 describe-volumes --region eu-west-2 --query 'Volumes[].VolumeId'
aws iam list-instance-profiles --path-prefix /karpenter/ --query 'InstanceProfiles[].InstanceProfileName'
```
