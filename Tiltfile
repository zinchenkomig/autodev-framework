allow_k8s_contexts('default')

# --- PostgreSQL ---
load('ext://helm_resource', 'helm_resource', 'helm_repo')
helm_repo('bitnami', 'https://charts.bitnami.com/bitnami')
helm_resource(
    'postgres',
    'bitnami/postgresql',
    resource_deps=['bitnami'],
    flags=[
        '--set', 'auth.username=autodev',
        '--set', 'auth.password=autodev',
        '--set', 'auth.database=autodev',
        '--set', 'primary.service.type=NodePort',
        '--set', 'primary.service.nodePorts.postgresql=30433',
    ],
)

# --- Redis ---
helm_resource(
    'redis',
    'bitnami/redis',
    resource_deps=['bitnami'],
    flags=[
        '--set', 'auth.enabled=false',
        '--set', 'master.service.type=NodePort',
        '--set', 'master.service.nodePorts.redis=30379',
        '--set', 'replica.replicaCount=0',
    ],
)

# --- AutoDev API ---
custom_build(
    'autodev-api',
    'docker build -t $EXPECTED_REF -f Dockerfile .',
    ['.'],
    disable_push=True,
)

k8s_yaml('k8s/api.yaml')
k8s_resource(
    'autodev-api',
    port_forwards=['8000:8000'],
    resource_deps=['postgres', 'redis'],
)

# --- Dashboard (future) ---
# k8s_yaml('k8s/dashboard.yaml')
# k8s_resource('autodev-dashboard', port_forwards=['3000:3000'])
