---
layout: page
title: "Cilium: 基于 BGP 和 L2 的 LoadBalancer IP 地址管理与宣告"
date: 2025-06-22 10:14:07
categories: Cilium
tags:
  - CNI
  - Cilium
  - 云原生
  - Kubernetes
---

​	Cilium 的强大之处不仅在于其 eBPF 数据平面的高性能，更在于它提供了一整套从网络连接、安全策略到服务暴露的云原生解决方案。在《[Cilium: 构建跨 BGP AS 域的 Kubernetes 集群网络](https://hihihiai.com/cilium/2025/07/02/cilium-bgpControlPlane.html)》文中，展示了其原生的 BGP 能力如何打通 Pod 网络。在此之上，本文将焦点放在服务的暴露上。本文将展示如何利用 Cilium 内置的 IPAM 功能为 LoadBalancer 服务自动分配 IP，并探讨如何配置 BGP 和 L2 两种通告方式，让这些服务 IP 像 Pod IP 一样，无缝地集成到网络基础设施中，彻底告别手动的网络配置和复杂的外部负载均衡器。

​	本文是《[Cilium: 构建跨 BGP AS 域的 Kubernetes 集群网络](https://hihihiai.com/cilium/2025/07/02/cilium-bgpControlPlane.html)》的续篇，放一起过于冗长才拆开。为确保能顺利理解文中的概念和操作，强烈建议先完成前一篇文章的学习。

## 一、使用 BGP 对 LB IP 进行通告 （BGP LB IPAM）

此功能简单来说，就是可以通过 BGP 把 LoadBalancer 类型的 Service IP 给通告出去。

首先需要修改一下 CiliumBGPPeeringPolicy 配置，让其限制哪些 Service 可以被宣告出去。

```
cat <<EOF | kubectl apply -f -
apiVersion: "cilium.io/v2alpha1"
kind: CiliumBGPPeeringPolicy
metadata:
  name: "rack0-65005"
spec:
  # 这个策略应用到哪些Kubernetes节点上。
  nodeSelector:
    matchLabels:
      rack: rack0
  virtualRouters:
    - localASN: 65005 # 这些Worker节点所在的 ASN
      # 能被这里匹配到的 Service 才能被宣告出去
      serviceSelector:
        matchLabels:
          advertise-bgp: "true"
      # 导出您想宣告的Pod CIDR。必须设置。
      exportPodCIDR: true
      # 定义BGP邻居（Peers）
      neighbors:
        - peerAddress: "10.0.5.1/24" # BGP RR 的IP地址
          peerASN: 65005 # BGP Peer 的ASN
---
apiVersion: "cilium.io/v2alpha1"
kind: CiliumBGPPeeringPolicy
metadata:
  name: "rack1-65010"
spec:
  # 这个策略应用到哪些Kubernetes节点上。
  nodeSelector:
    matchLabels:
      rack: rack1
  virtualRouters:
    - localASN: 65010 # 这些Worker节点所在的 ASN
      serviceSelector:
        matchLabels:
          advertise-bgp: "true"
      # 导出您想宣告的Pod CIDR。必须设置。
      exportPodCIDR: true
      # 定义BGP邻居（Peers）
      neighbors:
        - peerAddress: "10.0.10.1/24" # BGP RR 的IP地址
          peerASN: 65010 # BGP Peer 的ASN
EOF
```

然后需要配置地址池，即哪些 IP 可以被用于 LB 类型的 Service 的 IP：

也可以通过设置标签选择器来匹配哪些 Service 可以用那个池，这个具体可以看 CiliumLoadBalancerIPPool 的配置文档，这里就不演示了。

```
cat <<EOF | kubectl apply -f -
apiVersion: "cilium.io/v2alpha1"
kind: CiliumLoadBalancerIPPool
metadata:
  name: "lb-pool"
spec:
  blocks:
  - cidr: "20.0.10.0/24"
EOF
```

WorkLoad 和 Service 配置：

```
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
  labels:
    app: nginx
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  labels:
    # 只有匹配上 BGGP 的标签选择器，才会被通告。
    advertise-bgp: "true"
spec:
  selector:
    app: nginx 
  ports:
    - protocol: TCP
      port: 80 
      targetPort: 80
  type: LoadBalancer 
EOF
```

查看创建的 Service 情况：

```
root@server:~# kubectl get service
NAME            TYPE           CLUSTER-IP       EXTERNAL-IP   PORT(S)        AGE
kubernetes      ClusterIP      10.96.0.1        <none>        443/TCP        46h
nginx-service   LoadBalancer   10.102.158.224   20.0.0.100    80:30166/TCP   104s
```

从网络中 Client （非 K8S 节点）访问：

```
root@server:~# docker exec -it clab-cilium-bgp-client curl 20.0.0.100
<!DOCTYPE html>
<html>
<head>
<title>Welcome to nginx!</title>
<style>
html { color-scheme: light dark; }
body { width: 35em; margin: 0 auto;
font-family: Tahoma, Verdana, Arial, sans-serif; }
</style>
</head>
<body>
<h1>Welcome to nginx!</h1>
<p>If you see this page, the nginx web server is successfully installed and
working. Further configuration is required.</p>

<p>For online documentation and support please refer to
<a href="http://nginx.org/">nginx.org</a>.<br/>
Commercial support is available at
<a href="http://nginx.com/">nginx.com</a>.</p>

<p><em>Thank you for using nginx.</em></p>
</body>
</html>
```

查看通告情况（清理掉其他路由信息）：

```
root@server:~# docker exec -it clab-cilium-bgp-leaf01 route -n
20.0.0.100      10.0.5.11       255.255.255.255 UGH   20     0        0 eth1

root@server:~# docker exec -it clab-cilium-bgp-spine01 route -n
20.0.0.100      10.0.101.2      255.255.255.255 UGH   20     0        0 eth1
```

从这个路由信息来看，`20.0.0.100/32 gw 10.0.5.11` 被通告给了 leaf01，然后 spine01 从 leaf01 学习到了。

创建多个 Service 测试看看：

```
root@server:~# docker exec -it clab-cilium-bgp-leaf01 route -n
20.0.0.100      10.0.5.11       255.255.255.255 UGH   20     0        0 eth1
20.0.0.101      10.0.5.11       255.255.255.255 UGH   20     0        0 eth1
20.0.0.102      10.0.5.11       255.255.255.255 UGH   20     0        0 eth1
20.0.0.103      10.0.5.11       255.255.255.255 UGH   20     0        0 eth1
20.0.0.104      10.0.5.11       255.255.255.255 UGH   20     0        0 eth1
20.0.0.105      10.0.5.11       255.255.255.255 UGH   20     0        0 eth1
root@server:~# docker exec -it clab-cilium-bgp-leaf02 route -n
20.0.0.100      10.0.10.12      255.255.255.255 UGH   20     0        0 eth1
20.0.0.101      10.0.10.12      255.255.255.255 UGH   20     0        0 eth1
20.0.0.102      10.0.10.12      255.255.255.255 UGH   20     0        0 eth1
20.0.0.103      10.0.10.12      255.255.255.255 UGH   20     0        0 eth1
20.0.0.104      10.0.10.12      255.255.255.255 UGH   20     0        0 eth1
20.0.0.105      10.0.10.12      255.255.255.255 UGH   20     0        0 eth1
root@server:~# docker exec -it clab-cilium-bgp-spine01 route -n
20.0.0.100      10.0.101.2      255.255.255.255 UGH   20     0        0 eth1
20.0.0.101      10.0.101.2      255.255.255.255 UGH   20     0        0 eth1
20.0.0.102      10.0.101.2      255.255.255.255 UGH   20     0        0 eth1
20.0.0.103      10.0.101.2      255.255.255.255 UGH   20     0        0 eth1
20.0.0.104      10.0.101.2      255.255.255.255 UGH   20     0        0 eth1
20.0.0.105      10.0.101.2      255.255.255.255 UGH   20     0        0 eth1
root@server:~# docker exec -it clab-cilium-bgp-spine02 route -n
20.0.0.100      10.0.103.2      255.255.255.255 UGH   20     0        0 eth2
20.0.0.101      10.0.103.2      255.255.255.255 UGH   20     0        0 eth2
20.0.0.102      10.0.103.2      255.255.255.255 UGH   20     0        0 eth2
20.0.0.103      10.0.103.2      255.255.255.255 UGH   20     0        0 eth2
20.0.0.104      10.0.103.2      255.255.255.255 UGH   20     0        0 eth2
20.0.0.105      10.0.103.2      255.255.255.255 UGH   20     0        0 eth2
```

从测试情况来看，是匹配 Service 的 BGPP 的每个 AS 中，会选择一台 K8S Node 作为 LB 节点，然后所有的 LB 地址都从这个节点上面宣告出去。不同的 AS 会同时宣告 IP 的所有权。

## 二、使用 ARP 对 LB IP 进行通告（L2 LB IPAM）

> 此功能还在 Beta 阶段，如果生产环境使用，请优先考虑 MetalLB。
>
> 此功能需要开启 kubeProxyReplacement （Kube Proxy 替换模式）。
>
> 该功能与服务上的 `externalTrafficPolicy: Local` 不兼容，因为它可能导致服务 IP 在没有 pod 的节点上被宣布，从而引起流量中断。

在 BGP 环境，Cilium 可以采用 BGP 进行通告，但是如果不在 BGP 环境，或者没有启用`Set bgpControlPlane.enabled=true`，这个时候，就需要在 L2 层进行 IP 通告了，即通过 ARP 进行 IP 的通告。

由于 ARP/NDP 协议限制一个 IP 只能对应一个 MAC 地址，因此在集群中，必须指定单一节点来响应特定服务的 IP 请求。

Cilium 通过基于 Kubernetes 租约（Lease）的领导者选举来解决此问题。租约分配遵循“先到先得”原则，持有租约的节点即成为领导者，负责处理所有请求。但这种机制容易导致流量无法均匀分布。

通过选项`--set l2announcements.enabled=true` 启用。

配置通告规则和地址池，由于是 L2 层通告是以 ARP 形式通告 IP 给 L2 层网络，即 LB IPPool 需要为宿主机同网段 IP 。

```
cat <<EOF | kubectl apply -f -
apiVersion: "cilium.io/v2alpha1"
kind: CiliumLoadBalancerIPPool
metadata:
  name: "l2-pool-for-rack0"
spec:
  blocks:
    # 从 10.0.5.0/24 网段中选择一段未使用的地址
    #- cidr: "10.0.5.200/29"
    - start: "10.0.5.100"
      stop: "10.0.5.200"
  serviceSelector:
    matchLabels:
      # 与 CiliumL2AnnouncementPolicy 配合，只匹配 rack0 标签的机器。
      advertise-l2-rack0: "true"
---
apiVersion: "cilium.io/v2alpha1"
kind: CiliumL2AnnouncementPolicy
metadata:
  name: l2-lb-policy-for-rack0
spec:
  serviceSelector:
    matchLabels:
      # 和 CiliumLoadBalancerIPPool 匹配使用
      advertise-l2-rack0: "true"
  nodeSelector:
    matchLabels:
      # 如果集群建立在同一个 L2 ，这里可以专门选择几个用于 LB 的节点。
      rack: rack0
  interfaces:
  # 选择进行通告的网卡，不备注则所有网卡都对外通告。
  - ^net0$
  loadBalancerIPs: true
EOF

```

创建 Service 进行测试：

```
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
  labels:
    app: nginx
spec:
  replicas: 5
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  labels:
    advertise-l2-rack0: "true"
spec:
  selector:
    app: nginx 
  ports:
    - protocol: TCP
      port: 80 
      targetPort: 80
  type: LoadBalancer
EOF
```

Service 就会使用新的 IPPool：

```
root@server:~# kubectl get services
NAME            TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
kubernetes      ClusterIP      10.96.0.1       <none>        443/TCP        2d22h
nginx-service   LoadBalancer   10.110.163.14   10.0.5.100    80:30320/TCP   22s
```

由于是 L2 层通告，所以这里需要在 leaf01 下创建一个新的客户端，避免影响测试效果。

```
cat <<EOF > clab-test-client.yaml && clab deploy -t clab-test-client.yaml
name: cilium-bgp-test
mgmt:
  ipv4-subnet: 172.16.200.0/24
topology:
  nodes:
    leaf01-br:
        kind: bridge

    client2:
      kind: linux
      image: nicolaka/netshoot
      exec:
        - ip addr add 10.0.5.20/24 dev net0
        - ip route replace default via 10.0.5.1

  links:
   - endpoints: [client2:net0, leaf01-br:leaf01-br-eth4]
EOF
```

![image-20250704215333976](https://hihihiai.com/images/cilium-lb-ipam/image-20250704215333976.png)

查看通告情况：

```
root@server:~# docker exec -it clab-cilium-bgp-leaf01 arp -a
? (10.0.5.101) at aa:c1:ab:ce:e2:e4 [ether] on eth1
? (172.16.100.1) at 02:42:2e:c6:82:de [ether] on eth0
? (10.0.5.11) at aa:c1:ab:d6:55:7d [ether] on eth1
? (10.0.103.1) at aa:c1:ab:e2:bb:67 [ether] on eth3
? (10.0.101.1) at aa:c1:ab:07:b9:2e [ether] on eth2
? (10.0.5.100) at aa:c1:ab:ce:e2:e4 [ether] on eth1
? (10.0.5.12) at aa:c1:ab:ce:e2:e4 [ether] on eth1
? (10.0.5.20) at aa:c1:ab:8a:02:b8 [ether] on eth1
root@server:~# docker exec -it clab-cilium-bgp-leaf01 route -n
Kernel IP routing table
Destination     Gateway         Genmask         Flags Metric Ref    Use Iface
0.0.0.0         172.16.100.1    0.0.0.0         UG    0      0        0 eth0
10.0.5.0        0.0.0.0         255.255.255.0   U     0      0        0 eth1
10.0.10.0       10.0.101.1      255.255.255.0   UG    20     0        0 eth2
10.0.101.0      0.0.0.0         255.255.255.0   U     0      0        0 eth2
10.0.103.0      0.0.0.0         255.255.255.0   U     0      0        0 eth3
10.1.0.0        10.0.5.11       255.255.255.0   UG    20     0        0 eth1
10.1.1.0        10.0.101.1      255.255.255.0   UG    20     0        0 eth2
10.1.2.0        10.0.101.1      255.255.255.0   UG    20     0        0 eth2
10.1.3.0        10.0.5.12       255.255.255.0   UG    20     0        0 eth1
172.16.100.0    0.0.0.0         255.255.255.0   U     0      0        0 eth0
192.168.0.0     10.0.103.1      255.255.255.0   UG    20     0        0 eth3
root@server:~# docker exec -it clab-cilium-bgp-leaf02 arp -a
? (10.0.102.1) at aa:c1:ab:10:0f:de [ether] on eth2
? (10.0.10.12) at aa:c1:ab:52:1d:7d [ether] on eth1
? (172.16.100.1) at 02:42:2e:c6:82:de [ether] on eth0
? (10.0.10.11) at aa:c1:ab:16:0f:78 [ether] on eth1
? (10.0.104.1) at aa:c1:ab:07:c0:60 [ether] on eth3
```

只有 leaf01 的 ARP 表中有这个通告信息：**(10.0.5.100) at aa:c1\:ab:ce:e2:e4 [ether] on eth1**

Client2 上测试：

```
client2:~# for i in $(seq 1 20); do curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 3 http://10.0.5.100; done | sort | uniq -c | awk '{print "状态码 " $2 ": " $1 " 次"}'
状态码 200: 20 次
```

Client 上测试：

```
client:~# for i in $(seq 1 20); do curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 3 http://10.0.5.100; done | sort | uniq -c | awk '{print "状态码 " $2 ": " $1 " 次"}'
状态码 200: 20 次
```

虽然只在 L2 层通告，但是 10.0.5.0/24 网段被 BGP 通告过，所以 Client 能够访问到，如果 K8S 节点处于内网网段，而 Client 是公网的客户端，没有 BGP 通告 K8S 的内网网段出来，那么 Client 是无法访问到 LB IP 的。

至此，L2 层 LB IPAM 已经配置完毕，使用 Cilium CNI，只需要简单配置，K8S 节点就能够通过 L2 层进行 LB IP 的通告，算是一个非常方面的选择了。

#### kubeProxyReplacement DSR 测试

正好顺便测试一下 **kubeProxyReplacement DSR** 效果，具体原理细节看文章：[Cilium：基于 eBPF 的 Kube-Proxy 替代方案](https://hihihiai.com/cilium/2025/06/22/cilium-socketlb-dsr.html)

leaf02 抓去往 rack1 K8S 宿主机且与 Client2 相关的报文：

```
root@leaf02:/# sudo tcpdump -i eth3 -nn 'host 10.0.5.20'
```

在 Client2 上进行测试：

```
client2:~# curl http://10.0.5.100 > /dev/null 2>&1
client2:~# curl http://10.0.5.100 > /dev/null 2>&1
```

抓到报文：

```
root@leaf02:/# sudo tcpdump -i eth3 -nn 'host 10.0.5.20'
sudo: unable to resolve host leaf02: System error
tcpdump: verbose output suppressed, use -v[v]... for full protocol decode
listening on eth3, link-type EN10MB (Ethernet), snapshot length 262144 bytes
14:10:19.827228 IP 10.0.5.20.39246 > 10.1.1.134.80: Flags [S], seq 2858902172, win 56760, options [mss 9460,sackOK,TS val 2581696263 ecr 0,nop,wscale 7], length 0
14:10:19.827485 IP 10.0.5.100.80 > 10.0.5.20.39246: Flags [S.], seq 405849821, ack 2858902173, win 65160, options [mss 1460,sackOK,TS val 1033208525 ecr 2581696263,nop,wscale 7], length 0
14:10:19.827589 IP 10.0.5.20.39246 > 10.1.1.134.80: Flags [.], ack 405849822, win 444, options [nop,nop,TS val 2581696263 ecr 1033208525], length 0
14:10:19.827837 IP 10.0.5.20.39246 > 10.1.1.134.80: Flags [P.], seq 0:73, ack 1, win 444, options [nop,nop,TS val 2581696264 ecr 1033208525], length 73: HTTP: GET / HTTP/1.1
14:10:19.827961 IP 10.0.5.100.80 > 10.0.5.20.39246: Flags [.], ack 74, win 509, options [nop,nop,TS val 1033208526 ecr 2581696264], length 0
14:10:19.828577 IP 10.0.5.100.80 > 10.0.5.20.39246: Flags [P.], seq 1:239, ack 74, win 509, options [nop,nop,TS val 1033208526 ecr 2581696264], length 238: HTTP: HTTP/1.1 200 OK
14:10:19.828664 IP 10.0.5.20.39246 > 10.1.1.134.80: Flags [.], ack 239, win 443, options [nop,nop,TS val 2581696265 ecr 1033208526], length 0
14:10:19.828785 IP 10.0.5.100.80 > 10.0.5.20.39246: Flags [P.], seq 239:854, ack 74, win 509, options [nop,nop,TS val 1033208527 ecr 2581696265], length 615: HTTP
14:10:19.828841 IP 10.0.5.20.39246 > 10.1.1.134.80: Flags [.], ack 854, win 439, options [nop,nop,TS val 2581696265 ecr 1033208527], length 0
14:10:19.829346 IP 10.0.5.20.39246 > 10.1.1.134.80: Flags [F.], seq 73, ack 854, win 439, options [nop,nop,TS val 2581696265 ecr 1033208527], length 0
14:10:19.829661 IP 10.0.5.100.80 > 10.0.5.20.39246: Flags [F.], seq 854, ack 75, win 509, options [nop,nop,TS val 1033208528 ecr 2581696265], length 0
14:10:19.829739 IP 10.0.5.20.39246 > 10.1.1.134.80: Flags [.], ack 855, win 439, options [nop,nop,TS val 2581696266 ecr 1033208528], length 0
```

- 去向： **10.0.5.20.39246（ClientIP） > 10.1.1.134.80（PodIP）**
- 回向：**10.0.5.100.80（ServiceLBIP） > 10.0.5.20.39246（ClientIP）**

完美符合 DSR 特征。

## 结束语

​	至此，本文从 BGP 和 L2 两个维度，完整演示了如何配置 Cilium 来实现 LoadBalancer IP 的自动分配与宣告。回顾整个过程：在上一篇文章的基础上，仅仅通过简单的 CRD 配置，就为 Kubernetes Service 赋予了自动获取并向外部网络宣告其 IP 的能力。无论是对于需要三层路由的 BGP 环境，还是希望利用 ARP 的二层网络，Cilium 都提供了优雅且原生的解决方案。这不仅极大地简化了运维复杂度，也让 Kubernetes 集群与现有基础设施的集成变得前所未有的平滑和高效。
