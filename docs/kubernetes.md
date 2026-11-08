# Running on Kubernetes

How to run the service on a local kind cluster with the Helm chart.

## On Kubernetes, with kind

This runs the service on a local Kubernetes cluster, the same way it runs when deployed.
You need Docker, [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation),
[kubectl](https://kubernetes.io/docs/tasks/tools/) and
[Helm 4](https://helm.sh/docs/intro/install/). Set `POSTGRES_PASSWORD` in `.env` as for
[compose](../README.md#with-docker-compose).

Create the cluster and a namespace:

```sh
kind create cluster --name chapter-and-verse
kubectl create namespace chapter-and-verse
kubectl config set-context --current --namespace chapter-and-verse
```

Create two Secrets from `.env`, one value in each. Only the API pods read the Claude key.
The migrations get the database password only.

```sh
kubectl create secret generic postgres \
  --from-literal=password="$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"
kubectl create secret generic claude-api \
  --from-literal=CLAUDE_API_TOKEN="$(grep '^CLAUDE_API_TOKEN=' .env | cut -d= -f2-)"
```

Start Postgres. `deploy/kind/postgres.yaml` is for a local cluster only. A deployed
service uses a managed database.

```sh
kubectl apply -f deploy/kind/postgres.yaml
kubectl rollout status statefulset/postgres
```

Build the image and load it into the cluster. The kind node cannot see your local Docker
images:

```sh
docker build -t chapter-and-verse:dev .
kind load docker-image chapter-and-verse:dev --name chapter-and-verse
```

Install the chart:

```sh
helm upgrade --install chapter-and-verse charts/chapter-and-verse --wait
```

A Job applies the migrations first, then two API pods start. They run as a non-root user
with a read-only filesystem and pass the restricted Pod Security Standard. When a pod
stops, it finishes the requests it already has.

After a new build, load it again and run the same `helm upgrade` line to apply any new
migrations. Then run `kubectl rollout restart deployment/chapter-and-verse`. The tag
stays `dev`, so without the restart the pods keep the old image.

To reach the API, keep this running in its own terminal:

```sh
kubectl port-forward svc/chapter-and-verse 8000:8000
```

`kind delete cluster --name chapter-and-verse` removes everything, the stored answers
included.
