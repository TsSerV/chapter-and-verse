{{- define "cav.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "cav.image" -}}
image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
imagePullPolicy: {{ .Values.image.pullPolicy }}
{{- end }}

{{/* The migration Job and the API pods use the same database env. */}}
{{- define "cav.databaseEnv" -}}
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.passwordSecret.name }}
      key: {{ .Values.database.passwordSecret.key }}
# Kubernetes replaces $(DB_PASSWORD) when the container starts.
- name: DATABASE_URL
  value: "postgresql+asyncpg://{{ .Values.database.user }}:$(DB_PASSWORD)@{{ .Values.database.host }}:{{ .Values.database.port }}/{{ .Values.database.name }}"
{{- end }}

{{/* Passes the restricted Pod Security Standard. */}}
{{- define "cav.podSecurity" -}}
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "cav.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}
