---
layout: page
title: "Cilium: 深入解析 Cluster Mesh 的实现原理和跨集群通信机制"
date: 2025-07-12 10:14:07
categories: Cilium
tags:
  - CNI
  - Cilium
  - 云原生
  - Kubernetes
---

在业务规模尚小的时候，一个 Kubernetes 集群往往能撑起所有服务。但随着业务的扩张、多区域部署或故障域隔离的需求出现，多集群架构便成了必然选择。然而，集群一旦多了，新的问题就浮出水面：如何让分散在不同 Kubernetes 集群中的服务像在同一个局域网里一样方便、高效地通信？传统的 Ingress 暴露或者 VPN 方案，要么管理复杂，要么性能堪忧。Cilium Cluster Mesh 的出现，正是为了解决这个棘手的跨集群通信问题。本文将深入探讨 Cilium 如何利用 eBPF 技术，打通多个集群之间的网络脉络。

# 一、Cilium Cluster Mesh 是什么

![image-20250713200431541](https://hihihiai.com/images/cilium-cluster-mesh-datapathmode/image-20250713200431541.png)

Cilium Cluster Mesh 是 Cilium 提供的一种多集群解决方案。它能够将多个独立的，以 Cilium 为 CNI 的 Kubernetes 集群连接成一个“网格”（Mesh），使其在网络层面如同一个统一的大集群。在最优配置下，跨集群 Pod 间的通信性能几乎能与集群内通信相媲美。

这种模式不仅能有效隔离故障域，还为实现灰度发布、蓝绿部署等高级发布策略提供了一个新的方案。

借用一下官方的解释（上面的图也是官方文档中摘的。）：

- **高可用性和容错性：** Cluster Mesh 提高了服务的高可用性和容错能力。它支持在多个区域或可用区中运行 Kubernetes 集群。如果资源暂时不可用、某个集群配置错误或因升级而离线，它能够将操作切换到其他集群，确保服务始终可用。
- **透明服务发现：** Cluster Mesh 自动化了 Kubernetes 集群间的服务发现。通过使用标准的 Kubernetes 服务，它会自动将不同集群中同名同命名空间的服务合并为一个全局服务。这意味着您的应用程序可以跨集群发现和交互服务，极大地简化了跨集群通信。
- **无感知 Pod IP 路由：**Cluster Mesh 能在原生性能下处理多个 Kubernetes 集群之间的 Pod IP 路由。通过使用隧道传输或直接路由，它绕过了任何网关或代理的需要。这使得你的 Pod 能够无缝跨集群通信，从而提升整体的微服务架构效率。
- **跨集群共享服务：** Cluster Mesh 允许在所有集群之间共享诸如密钥管理、日志记录、监控或 DNS 等服务。这可以减少运营开销，简化管理，并保持租户集群之间的隔离。
- **统一网络策略执行：**Cluster Mesh 将 Cilium 的第 3 层-第 7 层网络策略执行扩展到网格中的所有集群。它标准化了网络策略的应用，确保在整个 Kubernetes 部署中采取一致的安全方法，无论涉及多少个集群。

# 二、Cilium Cluster Mesh 原理

Cilium Cluster Mesh 的架构遵循数据平面和控制平面两个部分。

## 控制平面

![image-20250713200452963](https://hihihiai.com/images/cilium-cluster-mesh-datapathmode/image-20250713200452963.png)

控制平面会提供所有 Pod 的信息。

在开启 Cilium Cluster Mesh 功能的集群，每个集群都会启动一个 clustermesh-apiserver，Cluster 里面会有两个容器，一个是 etcd ，一个是 Proxy，etcd 中存储着集群的特定信息，clustermesh-apiserver 通过 NodePort/LB 类型的 Service 对外提供服务。

当多个 Cluster 组成了 Mesh 的时候，各个集群的节点的 Cilium Agent，都会通过 TLS 连接到其他集群的 clustermesh-apiserver，并以只读的方式“监听”和“复制”相关的元数据。

clustermesh-apiserver 提供的数据包含：

- 全局服务 (Global Services): 哪些 Service 开启了 Mesh 级别的负载均衡，且负载均衡策略是什么。
- 身份和端点 (Identities & Endpoints): Identitie 是实现网络策略的基础，Endpoint 是 Pod 信息。
- 节点信息 (Nodes): Cluster Mesh 中所有节点的 IP 信息和其拥有的 PodCIDR 信息，用于建立跨集群的节点间网络连接。
- 网络策略 (Network Policies): 具体的网络策略信息，需要在 Mesh 内部进行同步。

## 数据平面

![image-20250713200507753](https://hihihiai.com/images/cilium-cluster-mesh-datapathmode/image-20250713200507753.png)

数据平面由运行在每个节点的 Cilium Agent 以及挂载在 Linux 内核的 eBPF 程序组成，

数据平面，数据平面从控制平面获取各个集群 Pod 信息，并在转发和收到的时候，分别进行网络策略的校验。

在集群内部时，Pod 与 Pod 间通信，还是会通过集群内配置策略，但是不同集群间通信，可以根据情况，采用不同的策略，但是集群网络模式和 Cluster Mesh 模式并不是可以随便组合的，后面会说明有哪些组合形式。

数据平面的作用：

- 高效负载均衡：让 CIlium 能在 Pod veth-pair tc ingress hook（from_container） 处或者 Socket 层（kubeProxyReplacement），就能把目标地址为 Global Service 的报文的目标 IP 改为其他集群的 Pod IP ，实现高效且便捷的跨集群负载均衡。
- 跨集群网络策略：虽然是多个集群组成的 Mesh，但是通过 CIlium ，整个 Cluster Mesh 都可以使用网络策略，和非 Mesh 一样，在 Overlay 架构下，每个报文在离开 Pod 时，其源 Cilium Identity 会被 eBPF 程序编码至报文中。在 Underlay 模式下，Pod 报文是直接发给目标 Pod 的，报文到达目标宿主机，在 redirect 给 Pod 前，Cilium eBPF 程序会通过之前在整个 Mesh 的集群的 clustermesh-apiserver 获取的信息，判断源 Pod 的 identity ，然后根据网络策略，放行或者 Drop 报文。
- **透明加密：** 支持使用 IPsec 或 WireGuard 对跨集群的流量进行透明的加密和解密

结合描述就是：

- **分布式信息同步**：首先，在每个成员集群中都会部署一个名为 `clustermesh-apiserver` 的核心组件。它负责收集并存储该集群内的 Pod、Service、Node、Identity 标识以及相关的网络策略信息。
- **构建全局视野**：随后，所有节点上的 Cilium Agent 会通过安全的 TLS 加密连接，从**所有集群**的 `clustermesh-apiserver` 中拉取信息，并将信息存储在当前节点的 eBPF map 中。这样，每个 Agent 就获得了整个 Cluster Mesh 的全局网络视野。
- **eBPF 流量重定向**：当 Pod 发起请求时，其网络报文会被内核中的 eBPF 程序高效拦截。如果请求的目标是一个全局服务（Global Service），eBPF 会绕过传统的 Service 代理，利用 DNAT 技术直接将目标 IP 改写为后端某个具体 Pod 的 IP。这个 Pod 可能在当前集群，也可能位于其他远程集群。这一步是 Cluster Mesh 的关键，因为它在 Cilium 层就实现了将 `Pod → Service` 的通信路径转变成了`Pod → Pod` 直连通信。
- **双向策略执行**：最后，在报文离开源节点前和进入目标 Pod 前，Cilium 都会进行严格的策略校验，根据预设的网络策略（Network Policy）来决定是放行还是拦截该流量，确保了端到端的安全。

# 三、Cilium Cluster Mesh 路径模式

正如集群内部需要 Overlay 或 Underlay 网络来实现 Pod 间通信一样，Cluster Mesh 也必须在集群之间建立可靠的通信链路。

具体采用哪种组网方案，则取决于现有条件，例如各集群间的网络连通性以及基础设施的限制。基于这些因素，Cluster Mesh 提供了隧道（Tunneling）和原生路由（Native Routing）等多种灵活的连接模式供用户选择。

## Cluster Mesh 有一些基础要求：

- 所有集群必须配置为相同的网络模式。
- 所有集群和所有节点中的 PodCIDR 范围必须不冲突且具有唯一的 IP 地址。
- 所有集群中的所有节点必须能够网络直达。

需要注意的是，所有集群必须配置相同的网络模式，并不只是 Cluster 内部，当需要在整个 Cluster Mesh 范围使用 IPSec 或者 WireGuard 进行封装时，Cluster 内部 Pod 间通信也需要先配置 IPSec 或者 WireGuard 封装。

## **隧道模式 (Tunnel Mode)：**

![image-20250713200523845](https://hihihiai.com/images/cilium-cluster-mesh-datapathmode/image-20250713200523845.png)

在 Cluster Mesh 采用 **Overlay** 模式时，报文会经过封装，其外层网络头体现为 **Node IP 到 Node IP** 的通信。因此，在这种模式下，对网络的基本要求被简化为：**只需保证节点（Node）与节点之间能够互相访问即可**。

### **通信策略**

- **非加密情况** 如果在 Cluster Mesh 层面不指定加密配置（即 Pod 跨集群通信不加密），那么跨集群通信便会**采用与集群内部完全相同的通信策略**，无论是 Native Routing 还是 VXLAN 模式。
- **加密情况** 启用跨集群加密有一个明确的前提条件：**集群内部的网络本身必须已经配置为 IPSec 或 WireGuard 模式**。只有在此基础上，Cluster Mesh 才能同样启用 IPSec 或 WireGuard 进行跨集群加密通信。

### **隧道模式总结**

将 VXLAN、IPSec 或 WireGuard 用作 Cluster Mesh 的通信模式，我们将其**统称为隧道模式**。

在隧道模式下，底层网络只会看到发生在节点与节点之间的通信。这样一来，虽然报文封装增加了网络开销，但也极大地降低了对网络的要求——只需保证 Cluster Mesh 内的所有节点间能够互相通信即可。

## 优缺点：

**优点：**

- **简化网络要求**: 无需底层网络支持 Pod IP 的路由。只需确保各集群的所有节点之间网络互通，极大降低了网络配置的复杂性。
- **Pod IP 地址透明**: Pod 的 IP 地址对底层网络是不可见的，网络设备只会看到节点 IP 之间的流量。这有助于简化防火墙规则的配置，并能有效避免云环境中 VPC 的 IP 地址冲突问题。

**缺点：**

- **性能开销与吞吐量下降**: 报文封装会增加额外的网络头（Overhead），这会占用一部分带宽，从而降低网络的理论最大吞吐量。在标准 MTU（1500字节）环境下，这种性能损耗比在巨型帧（Jumbo Frames, 9000字节）环境下更为显著。
- **依赖硬件卸载功能**: 为了避免因封装和解封装操作（如校验和计算、分段）消耗大量 CPU 资源，隧道模式高度依赖网络接口（NIC）的硬件卸载（Hardware Offload）功能，例如校验和卸载（Checksum Offload）和分段卸载（Segmentation Offload）。幸运的是，现代服务器硬件已普遍支持这些功能。

## 原生路由（Native Routing）**：**

![image-20250713200657907](https://hihihiai.com/images/cilium-cluster-mesh-datapathmode/image-20250713200657907.png)

要使用原生路由模式的 Cluster Mesh，必须满足以下先决条件：

1. **集群内部模式**：所有成员集群的内部网络模式必须是 `Native Routing`。
2. CIDR 覆盖：所有集群的 Pod IP 地址范围（PodCIDR）都必须被 `ipv4NativeRoutingCIDR` 这个配置参数所覆盖。
   - **重要说明**：任何目标地址**不在** `ipv4NativeRoutingCIDR` 范围内的流量，都会被 Cilium 进行 **SNAT**（源地址转换），伪装成节点 IP 发出。在大规模流量下，这会因`conntrack`表的维护和地址转换本身带来显著的性能损耗。
3. **底层网络能力**：底层网络基础设施必须具备直接处理和转发 Pod 到 Pod 流量的能力。

### 通信原理：

由于 Cilium 将路由责任交给了底层网络，实现 Pod IP 在整个 Mesh 内互通主要有两种方案，具体取决于集群间的网络拓扑。

**方案一：集群位于同一 L2 网络**

当所有需要互联的集群节点都位于同一个二层（L2）广播域时（例如，同一个VLAN），可以采用较为简单的静态路由方案。

- **工作原理**：通过启用 `auto-direct-node-routes=true` 配置，Cilium 会自动在每个节点上添加静态路由规则。这些规则会指明**其他集群的 PodCIDR 应通过其对应的节点 IP 来访问**。
- **报文流转**：这样，当一个 Pod 发往其他集群的 Pod 时，报文在离开源节点后，能够在 L2 网络中被直接转发到目的 Pod 所在的目标节点，实现了 Pod 到 Pod 的直接通信。

**方案二：Cilium 通过 BGP 通告 PodCIDR**

当集群分布在不同的网络（例如，不同的数据中心、VPC），彼此之间通过三层（L3）路由器连接时，静态路由不再可行，此时需要动态路由协议。

- **工作原理**：利用 **BGP** 让每个集群的 Cilium Agent 作为 BGP Speaker，向其上层网络 BGP 路由反射器宣告自己所负责的 PodCIDR。
- **报文流转**：上层路由器通过学习 BGP 路由，就能构建出完整的 Pod IP 路由表，获知每一个 PodCIDR 背后对应的节点信息。当一个跨集群的 Pod 报文到达路由器时，路由器能够根据这个全局路由表，**在 L3 层面正确地将其转发到目标 Pod 所在的节点**。

### 优缺点：

### **优点：**

- **高性能**：消除了隧道封装的开销（CPU 和网络带宽），提供接近物理网络的延迟和吞吐量。

### **缺点：**

- **对底层网络依赖强**：将配置复杂性转移到了网络基础设施，需要结合网络架构进行规划。

## 四：Global Service 跨集群 Pod

关于从 Global Service 到跨集群 Pod 的流量转发机制，上面其实已经说过一遍了，但是这里还是需要特别说明一下。

首先需要了解 Cilium 是如何使用 eBPF 替代 Kube-Proxy 的：[Cilium：基于 eBPF 的 Kube-Proxy 替代方案](https://hihihiai.com/cilium/2025/06/22/cilium-socketlb-dsr.html)

1. **标准路径**：在 Kubernetes 中，`Pod → Service → Pod` 的流量转发通常由 `Kube-Proxy` 在节点内核中完成。
2. **Cilium 的默认行为**：在 Cilium 环境下，如果未启用 `kubeProxyReplacement` 功能，Cilium 默认也会沿用 `Kube-Proxy` 来处理上述流量。
3. **问题所在**：然而，完全依赖 `Kube-Proxy` 的方式，会给 Cilium Cluster Mesh 的 `Global Service`功能带来实现上的困难，不但侵入性大，而且整个处理逻辑也不只是在局限在 CNI 层。
4. **Cilium 的解决方案**：为了确保 `Global Service` 正常工作，只要开启了 `Cluster Mesh`（集群网格），Cilium 就会进行干预。即使 `kubeProxyReplacement` 未开启，Cilium 依然会在数据包进入 Pod 的网络接口时（具体在 `veth-pair` 的 `tc ingress hook` 处），主动将 `Global Service` 的 IP 地址直接转换为最终目标 Pod 的 IP 地址。

## 总结语

总而言之，Cilium Cluster Mesh 通过同步 Service/Endpoint 与利用底层流量隧道技术，巧妙地构建了一个跨越多个 Kubernetes 集群的统一“扁平网络”。这不仅使得身处不同集群的服务能像邻居一样，通过标准 Service 名称直接通信，更将网络策略（Network Policy）的能力扩展至整个 Cluster Mesh，实现了统一的安全隔离与访问控制。最终，使用者可以忽略底层网络的复杂性，获得无缝且安全的跨集群服务体验。
