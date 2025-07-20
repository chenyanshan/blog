---
layout: page
title:  "Istio 基础安装和使用"
date:  2025-05-11 10:14:07
categories: ServiceMesh
tags:
  - 服务网格
  - istio
  - 云原生
  - Kubernetes
---

在当前的云原生时代，微服务架构和容器化部署已经成为主流。然而，随着服务数量的指数级增长，如何有效地管理、连接、保护和观察这些分布式服务，成为了摆在每一位工程师面前的现实挑战。Istio，作为一个功能强大的开源服务网格，应运而生，为解决这些复杂问题提供了一套全面的解决方案。

说到 Istio，对于已经遨游在 Kubernetes 和微服务浪潮中的工程师来说，恐怕不会陌生。它通过在服务旁部署轻量级代理（Sidecar），实现了对服务间流量的精细控制、强大的安全策略以及丰富的遥测数据收集，而这一切对应用代码几乎是透明的。然而，Istio 的功能虽然强大，其学习曲线也相对陡峭。本篇文章，我们将聚焦于 Istio 的基础部分，从零开始，一步步探讨其核心概念，并完成基础环境的安装与初步使用，为后续更深入的学习和实践打下坚实的基础。

[文章提及的配置和代码](https://github.com/chenyanshan/LearningManifests/tree/main/6-istio-%E5%9F%BA%E7%A1%80%E6%BC%94%E7%A4%BA)

## 一、istio 的安装

### 1. 安装方式介绍

主流的 istio 安装方式分 `istioctl` 和 `Helm` 两种。`istioctl` 作为 Istio 官方推荐的工具，其优势在于提供了强大的配置验证、与 `IstioOperator` API 的紧密集成以及针对不同环境的自动检测能力，确保了安装的可靠性和安全性；但可能需要管理不同版本的二进制文件。相较而言，`Helm` 的优势在于能够轻松融入现有的 Helm 生态系统，利用其成熟的发布和升级管理功能，并能自动修剪旧资源；然而，它在安装时的检查和验证不如 `istioctl` 全面，且某些特定管理任务可能更为复杂。

这里使用`istioctl`进行演示，`istioctl` 有 `profile` 的概念，在安装的时候指定不同的 `profile` 就能安装不同的组件，下面是其 `profile` 组件对应安装的组件图。

|                        | default | demo | minimal | remote | empty | preview | ambient |
| ---------------------- | ------- | ---- | ------- | ------ | ----- | ------- | ------- |
| 核心组件               |         |      |         |        |       |         |         |
| `istio-egressgateway`  |         | ✔    |         |        |       |         |         |
| `istio-ingressgateway` | ✔       | ✔    |         |        |       | ✔       |         |
| `istiod`               | ✔       | ✔    | ✔       |        |       | ✔       | ✔       |
| `CNI`                  |         |      |         |        |       |         | ✔       |
| `Ztunnel`              |         |      |         |        |       |         | ✔       |

为了不一次性引入太多概念，这里只需要关注这两个组件：

- `istiod`: 核心控制平面组件，负责服务发现、配置分发、证书管理等。

- `istio-ingressgateway`: 入口网关，用于管理进入网格的流量。

### 2. 安装 istio

#### 我的环境：

- `Kubernetes`: v1.30
- `istioctl`: 1.25.2

需要注意的是，Istio 的版本对于 Kubernetes 的版本有要求，即固定 Kubernetes 版本，只能安装某些版本的 Istio，这是具体的对应关系表：[Istio 和 Kubernetes 版本支持关系](https://istio.io/latest/docs/releases/supported-releases/)

也可以使用 `istioctl x precheck` 命令来检查 Kubernetes 版本是否适合安装或升级 Istio。

#### 下载和安装

- 下载安装最新版本：

```bash
~$ curl -L https://istio.io/downloadIstio | sh -
~$ cd ~/istio-1.26.0/
~/istio-1.26.0$ ls
bin  LICENSE  manifests  manifest.yaml  README.md  samples  tools
```

可以通过把 `bin/istioctl`  复制到 `/usr/local/bin` 下，或者通过在在环境变量中增加`export PATH="$PATH:/home/ubuntu/istio-1.26.0/bin"` 完成安装。

如果上面命令无法下载 `istio` ，可以去 [Istio Github Releases 页面](https://github.com/istio/istio/releases/tag/1.26.0) 下载，解压后也是同样流程安装。

- 下载指定版本的 `istioctl`:

```bash
$ curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.26.0 TARGET_ARCH=x86_64 sh -
```

其他操作流程还是和上面类似。

- 安装 istio 到集群。

```
$ istioctl install --set profile=default -y
```

这里指定的 `profile`是`default`，可以按需修改，这里安装的`istio`并不会出现镜像拉取问题。

使用的名称空间为 `istio-system`

- 安装 istio 到指定集群。

``` bash
$ istioctl install --kubeconfig=/home/ubuntu/.kube/test-cluster-kueconfig --set profile=default -y
```

`istioctl` 也支持 `--kueconfig` 命令。

- 卸载 istio。

```bash
$ istioctl uninstall -y --purge
```

Istio 卸载程序按照层次结构逐级地从 `istio-system` 命令空间中删除 RBAC 权限和所有资源。

最后再手动将`istio-system`名称空间删除即可。



## 二、演示环境



这里简单使用两个 nginx deployment 来演示，还有一个用户测试的 client pod 。

Namespace:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: istio-test
  labels:
    istio-injection: enabled   # 开启 istio sidecar 注入
```

Nginx Deployment: 

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-v1
  namespace: istio-test
  labels:
    app: nginx
    version: v1
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx
      version: v1
  template:
    metadata:
      labels:
        app: nginx
        version: v1
    spec:
      initContainers:
      - name: init-html-generator
        image: busybox:latest
        env:
        - name: VERSION
          value: "v1"
        command: ['sh', '-c']
        args:
        - |
          echo "${VERSION}" >> /usr/share/nginx/html/index.html
          echo "${VERSION}" >> /usr/share/nginx/html/test.html
        volumeMounts:
        - name: shared-html
          mountPath: /usr/share/nginx/html
      containers:
      - name: nginx-server
        image: nginx:latest
        ports:
        - containerPort: 80
        volumeMounts:
        - name: shared-html
          mountPath: /usr/share/nginx/html
      volumes:
      - name: shared-html
        emptyDir: {}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-v2
  namespace: istio-test
  labels:
    app: nginx
    version: v2
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx
      version: v2
  template:
    metadata:
      labels:
        app: nginx
        version: v2
    spec:
      initContainers:
      - name: init-html-generator
        image: busybox:latest 
        env:
        - name: VERSION
          value: "v2"
        command: ['sh', '-c']
        args:
        - |
          echo "${VERSION}" >> /usr/share/nginx/html/index.html
          echo "${VERSION}" >> /usr/share/nginx/html/test.html
        volumeMounts:
        - name: shared-html
          mountPath: /usr/share/nginx/html
      containers:
      - name: nginx-server
        image: nginx:latest
        ports:
        - containerPort: 80
        volumeMounts:
        - name: shared-html
          mountPath: /usr/share/nginx/html
      volumes:
      - name: shared-html
        emptyDir: {}
```

Nginx Service:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx
  namespace: istio-test
spec:
  selector:
    name: nginx
  type: ClusterIP
  ports:
  - name: http
    protocol: TCP
    port: 80
    targetPort: 80
```

Client:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: client
  namespace: istio-test
spec:
  containers:
  - name: client
    image: alpine:latest
    command: ["tail"]
    args: ["-f", "/dev/null"]
```

安装完：

```
$ kubectl get pods,service -n istio-test
NAME                            READY   STATUS    RESTARTS   AGE
pod/client                      2/2     Running   0          91s
pod/nginx-v1-b4ff868f4-xgwzw    2/2     Running   0          33s
pod/nginx-v2-5ff55845cb-tf5s4   2/2     Running   0          33s

NAME            TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)   AGE
service/nginx   ClusterIP   172.16.38.9   <none>        80/TCP    104s

$ kubectl exec -it client -n istio-test -- /bin/sh
/ # wget -qO - nginx/test.html
v1
/ # wget -qO - nginx/test.html
v2
/ # wget -qO - nginx
v2
```

可以看到 Pod Ready 状态的值都是 2，这是因为还有一个 `istio-proxy` 容器被注入到当前名称空间的所有 Pod 中。



## 三、最基础的 VirtualService 和 DestinationRule

DestinationRule（DR）：定义了当流量*已经*被 VirtualService 路由到某个具体的目标服务后，应该如何处理这些流量。它关注的是客户端如何与目标服务的实例进行交互。

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: nginx
  namespace: istio-test
spec:
  # host 字段指定了此 DestinationRule 将应用于哪个服务。
  # 通常这是 Kubernetes 服务的 FQDN 。
  # 格式为: <service-name>.<namespace>.svc.cluster.local
  # 或者，如果 DestinationRule 与服务在同一个命名空间，可以直接使用服务名：<service-name>
  host: nginx
```

VirtualService（VS）：定义了当流量到达某个特定的主机（或一组主机）时，应该如何被路由。

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: nginx
  namespace: istio-test
spec:
  # hosts 字段定义了此 VirtualService 将应用于哪些虚拟主机。
  # 这通常是客户端用来访问服务的地址。
  hosts:
  - nginx
  http:
  - route:
    - destination:
        host: nginx   # 传递给 spec.host 为 nginx 的 DestinationRule。
```

上面的  VirtualService 和 DestinationRule 虽然是最基础的配置，但是它也明确地声明了流量应该如何被 Istio 处理。后续的高级流量治理功能就会在此基础上进行配置。

在 Client 上测试请求，效果和没有 VS，DR 一致。

## 四、istio 流量治理

这里将对两个 Nginx 不同版本进行区分，然后通过流量控制，让请求流向指定的版本。

**DestinationRule（DR）**:

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: nginx
  namespace: istio-test
spec:
  host: nginx
  subsets:   # 定义目标服务命名子集
  - name: appv1
    labels:
      version: v1 # 对 service 后端的 pod 进一步筛选。
  - name: appv2
    labels:
      version: v2 
```

**`subsets`**: 这个字段用于定义目标服务的命名子集。每个子集通常代表了该服务的一个特定版本、一个特定的部署配置（例如金丝雀版本、蓝绿部署中的一个环境等）。这些子集随后可以被 `VirtualService` 用来做更细粒度的流量路由。

上面的配置定义了两个子集，subset appv1 会把流量转给 v1 版本的 pod ，subset appv2 会把流量转给 v2 版本的 pod。

### 4.1 根据权重进行路由

- 所有流量都指向 v1 版本：

  ```yaml
  apiVersion: networking.istio.io/v1alpha3
  kind: VirtualService
  metadata:
    name: nginx
    namespace: istio-test
  spec:
    hosts:
    - nginx
    http:
    - route:
      - destination:
          host: nginx
          subset: appv1
  ```

  上面的配置相较于一开始的配置，就只多了一项，就是 subset: appv1 。

  效果：在配置此 vs 前，请求还是 v1/v2 随机出现，配置此 vs 后，只请求到了 v1 。

- 流量按权重请求到 v1 和 v2 ：

  ```yaml
  apiVersion: networking.istio.io/v1alpha3
  kind: VirtualService
  metadata:
    name: nginx
    namespace: istio-test
  spec:
    hosts:
    - nginx
    http:
    - route:
      - destination:
          host: nginx
          subset: appv1
        weight: 30
      - destination:
          host: nginx
          subset: appv2
        weight: 70
  ```

  效果：

  ```bash
  $ kubectl exec -it client -n istio-test -- /bin/sh
  / #
  / # (echo -n "正在请求 (共100次): " >&2; for i in $(seq 1 100); do echo -n "." >&2; wget -qO - -T 2 -t 1 nginx 2>/dev/null; done; echo " 完成!" >&2) | awk 'BEGIN{count_v1=0; count_v2=0} $0=="v1"{count_v1++} $0=="v2"{count_v2++} END{print "\n--- 结果 ---"; print "请求到 v1 的次数: "
  count_v1; print "请求到 v2 的次数: " count_v2}'
  正在请求 (共100次): .................................................................................................... 完成!
  
  --- 结果 ---
  请求到 v1 的次数: 23
  请求到 v2 的次数: 77
  ```



### 4.2 根据请求路径和请求首部进行路由

配置的 VS：

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: nginx
  namespace: istio-test
spec:
  hosts:
  - nginx
  http:
  - match: # 规则1: 匹配特定头部
    - headers:
        test:
          regex: "true"
    route:
    - destination:
        host: nginx
        subset: appv2
  - match: # 规则2: 路径匹配
    - uri:
        prefix: "/test.html"
    route:
    - destination:
        host: nginx
        subset: appv2
  - route:  # 默认给 v1
    - destination:
        host: nginx
        subset: appv1
```

上面的配置采用两种规则进行匹配:

- http header 有 test 首部且值为 true 即路由到 v2 。
- 请求 url 为 "/test.html" 即路由到 v2 。
- 什么都没有匹配到默认路由到 v1 。

效果：

```yaml
$ kubectl exec -it client -n istio-test -- /bin/sh
/ # wget -qO - --header="test: true" nginx
v2
/ # wget -qO - --header="test: true" nginx
v2
/ # wget -qO - nginx/test.html
v2
/ # wget -qO - nginx
v1
/ # wget -qO - nginx
v1
```

### 五、集群外部流量接入

上面的流量都是在集群内部流通，现在需要将服务发布到集群外部。这里准备使用 `Gateway` 资源，不过需要注意的是，在 Istio 的生态中，当我们提及"`Gateway`"时，需要注意区分两种主要的资源定义：

- **Istio Gateway (Istio 原生的 CRD)**:
  - Istio 项目原生 CRD，是 Istio 中管理网关行为的传统且核心的方式。
  - `apiVersion` 隶属于 `networking.istio.io` API 组
- **Kubernetes Gateway API (`Gateway` 资源)**:
  - 这是一个由 Kubernetes 社区推动的、旨在标准化网关和入口流量配置的较新API规范。
  -  `apiVersion` 隶属于 `gateway.networking.k8s.io` API 组
  - Istio 对其做了兼容和支持，可以使用 Kubernetes Gateway API 中的 `Gateway`、`HTTPRoute` 等资源，并选择 Istio 作为其`gatewayClass`，从而可以通过 Istio 管理入口流量。

这里我们使用`Istio Gateway`。

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: Gateway
metadata:
  name: nginx-test-gateway
  namespace: istio-test
spec:
  selector:
  # 此处是配置的具体使用哪个 ingressgateway pod 。
  # 此处是选中了 istio-system 中标签包含 istio: ingressgateway 的 pod 。
    istio: ingressgateway
  servers:
  - port:
      number: 80
      name: http
      protocol: HTTP
    hosts:
    - '*.hihihiai.com'
```

这里是一个只配置`HTTP` 的简单的`Gateway` 资源。

选中的是下面的 Pod 。

```bash
$ kubectl get pods -l istio=ingressgateway -n istio-system
NAME                                    READY   STATUS    RESTARTS   AGE
istio-ingressgateway-54b88fc78b-7f4f2   1/1     Running   0          22d

$ kubectl get services -l istio=ingressgateway -n istio-system
NAME                   TYPE           CLUSTER-IP     EXTERNAL-IP       PORT(S)                                                                      AGE
istio-ingressgateway   LoadBalancer   172.16.35.58   111.111.111.111   15021:30532/TCP,80:31117/TCP,443:31408/TCP,31400:31791/TCP,15443:31023/TCP   22d
```

同时，如果要将业务暴露到外部，需要将 `Service/istio-ingressgateway` 暴露出去。

外部流量会通过`Service/istio-ingressgateway` 进来，然后进入`istio-ingressgateway`，然后被我们配置`VirtualService` 匹配并路由给真正的业务端点。

VirtualService 配置:

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: nginx
  namespace: istio-test
spec:
  hosts:
  - "nginx.hihihiai.com"  # 匹配的域名。
  - "nginx"               # 为内部转发而配置。
  gateways:               # VS 生效的位置
  - nginx-test-gateway    # 此 Gateway 资源选中的 istio ingressgateway pod 。
  - mesh                  # 专用名词，网格内部，网格内部所有 Pod 都会生效。
  http:
  - route:
    - destination:
        host: nginx
        subset: appv1
      weight: 30
    - destination:
        host: nginx
        subset: appv2
      weight: 70
```

`gateways: - mesh` 这个配置，如果不指定 `gateways`配置项，是默认就会生效的，即此 VS 在网格内所有 Pod 上都生效，如果指定了`gateways`，没有显式配置`mesh`，那么此 VS 就只会在选择的`ingressgateway`上生效，实际上，内部使用 VS 和外部使用 VS 可以区分开，只需要注释掉 `mesh` 即可。

效果（外部机器请求）:

```
$ (echo -n "正在请求 (共100次): " >&2; for i in $(seq 1 100); do echo -n "." >&2; curl -H"Host: nginx.hihihiai.com" http://<istio-ingressgateway-service-ip-port> 2>/dev/null; done; echo " 完成!" >&2) | awk 'BEGIN{count_v1=0; count_v2=0} $0=="v1"{count_v1++} $0=="v2"{count_v2++} END{print "\n--- 结果 ---"; print "请求到 v1 的次数: "count_v1; print "请求到 v2 的次数: " count_v2}'
正在请求 (共100次): .................................................................................................... 完成!

--- 结果 ---
请求到 v1 的次数: 31
请求到 v2 的次数: 69
```

如果要测试，需要将 `<istio-ingressgateway-service-ip-port>` 替换成自己 Service 暴露出来的 IP 和 端口。



## 结束语

通过本文的介绍，我们应该对 Istio 的基础安装和初步使用有了大致的了解，从准备环境到部署 Istio 控制平面，再到将示例应用纳入服务网格进行管理，我们体验了 Istio 最基本的工作流程。这仅仅是 Istio 世界的冰山一角，我们触碰到的更多是其“如何工作”的表面现象。

当然，Istio 的功能远不止于此。诸如更复杂的流量路由规则（如金丝雀发布、A/B测试）、强大的故障注入与恢复能力、细致的安全策略（认证与授权）、以及与 Prometheus、Grafana、Jaeger 等工具集成的全方位可观测性等高级特性，还有和各种 Rollout CRD 结合的高级发布策略，都是 Istio 在生产环境中大放异彩的关键。掌握 Istio 并非一蹴而就，后续我们将进一步探讨这些高级功能，并结合实际场景进行更深入的剖析和实践。对于更详尽的配置选项和更深层次的原理，还是建议大家多查阅官方文档，并在实践中不断摸索。
