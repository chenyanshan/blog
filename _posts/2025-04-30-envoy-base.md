---
layout: page
title:  "Envoy 核心架构浅述"
date:  2025-04-30 22:14:07
categories: 云原生
tags:
  - 服务网格
  - Envoy
  - Istio
  - 云原生
---

Envoy 是现代服务网格基石，在服务网格应用场景，还是需要对了解 Envoy 架构和其工作原理，才能在问题出现时，在控制平面之前的更底层---数据平面，对故障进行排查。

对于增加网络复杂度的服务网格，还是需要慎重对待，熟悉其原理，才能在遇到问题时游刃有余。



# 一、 Envoy 在云原生架构中的作用

Envoy 在云原生架构中，会担任两个角色，一是 ingress gateway 的流量管理器，二是服务网格的数据平面。那它为什么会成为这两个角色中的核心组件呢？

原因是因为 Envoy 的特性，Envoy 就是云原生场景的 Nginx 。

Envoy 特性：

- 高性能，C++ 研发，多年打磨。
- 支持几乎所有的 TCP/UDP/HTTP Proxy 所能拥有的功能，而且还原生支持很多较为通用的七层协议，例如 Redis、MongoDB、Dubbo、MySQL 等。
- 支持通过 xDS 动态加载配置并动态应用最新配置。
- 支持用户自定义“插件”（Envoy Filter），允许通过 L4 或 L7 Filter 扩展功能。
- 开箱即用的分布式追踪和相关统计功能。
- 支持很多高级特性，例如：熔断、限流、重试、超时、故障注入、流量管理、区域感知路由等等。

动态、分布式、API 驱动 ，让其他产品在实现 ingress gateway 和服务网格的时候，无需实现各项流量管理功能，只需要生成配置，并将配置交由 Envoy ，然后就能实现相关功能，并且稳定且性能强大，如果自己再去实现相关功能，就相当于重新造轮子，而且基本上不可能有现有的轮子好用，所以 Envoy 已经成为了云原生时代默认的实际流量管理工具。



# 二、Envoy 架构

![envoy-base-workflow](http://hihihiai.com/images/envoy-base/envoy-base-workflow.png)

<center>Envoy 基础架构图</center>



Envoy 的配置由 监听器（Listeners）、过滤器链（Filter Chains）、路由（Route）、集群（Clusters）、端点（Endpoint） 组成。

- Listeners：一个 Envoy 实例可以有多组监听器，而每个监听器可以监听不同的 IP 地址和端口，处理不同类型的流量。单个侦听器自成一个整体。
- Filter Chains： 过滤链，过滤器链是连接与监听器下的组件，即每个监听器都会因为业务不同有自己的过滤器链处理自己的业务。而为什么叫做链呢？是因为一个监听器可以配置一个或者多个过滤器，从而形成过滤器链。有比如 tcp_proxy，rate_limit，其中最重要的是 http_connection_manager（HCM），HTTP 连接管理链。
- Route: 路由，HTTP 过滤器，是 HCM 过滤器的核心功能，根据路径，域名，将流量转发到后端的 Cluster 。
- Clusters： 集群，可以指定负载均衡策略，连接超时设置，将流量转发给一组 Endpoint 。
- Endpoint： 端点，真正的业务节点地址。

它们是如何协同工作的？
1. 一个请求进来，经过监听器。
2. 监听器的过滤器链处理请求。如果是 HTTP 流量，http_connection_manager 会接管（如果配置了 HCM 的情况下）。
3. http_connection_manager 根据请求的特征和它内部的 route_config 中的路由规则进行匹配。
4. 路由规则匹配成功后，会指定一个目标集群。
5. Envoy 接下来就会将这个请求发送到指定的集群。
6. 在将请求发送到集群时，Envoy 会根据该集群配置的负载均衡策略（比如轮询、随机、最少请求等），从集群中的多个服务实例（Endpoints）中选择一个来发送请求。

其实 Envoy 就相当于一个 Nginx ，但是有 Nginx 不能实现的很多高级功能罢了。

xDS: DS 配置自动发现：

​	因为有多种配置自动发现，所以叫 xDS ，xDS 中有多种配置发现，有 LDS、CDS、RDS、EDS、SDS 等。即，我们可以通过 xDS 机制，动态修改 Envoy 的所有配置。这也是 Envoy 成为通用流量管理工具的原因，因为你只需要把用户需求“翻译”成 Envoy 的配置文件，下发给 evnoy ，即可实现 Envoy 所拥有的所有功能。例如，你需要实现一个带有很多高级功能的 ingress 控制器，你只需要把 ingress 的配置，翻译成 Envoy 的配置，然后通过 xDS 发下给 Envoy 即可。

# 三、基础 Envoy 示例
这里给一个简单的 Envoy 示例，演示一下 Envoy 的大致工作原理。 [下面演示的配置文件位置](https://github.com/chenyanshan/LearningManifests/tree/main/4-envoy%E5%9F%BA%E7%A1%80%E7%A4%BA%E4%BE%8B)

这里提供的 envoy 配置都是静态配置，但是这里面的所有配置，都可以通过 xDS 获取。

```
✗ tree
.
├── docker-compose.yaml
├── envoy.yaml
├── nginx1
│   ├── index.html
│   └── test.html
└── nginx2
    ├── index.html
    └── test.html
```

envoy.yaml：

```yaml
static_resources:
  listeners:
  - name: listener_0
    address:
      socket_address: { address: 0.0.0.0, port_value: 80 } # Envoy 监听在所有 IP 的 80 端口
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: ingress_http
          route_config: # 路由配置
            name: local_route
            virtual_hosts: # 基于 Host 头的虚拟主机列表
            - name: web_service_1
              domains: ["*.hihihiai.com", "hihihiai.com"] # 匹配 hihihiai.com 及其子域名
              routes:
              - match: { prefix: "/" } # 匹配所有路径
                route: { cluster: local_cluster } # 路由到 local_cluster
            - name: web_service_2
              domains: ["*.test.com","test.com"] # 匹配 test.com 及其子域名
              routes:
                - match: { prefix: "/test.html" } # 匹配 /test.html 路径
                  route: { cluster: nginx_service_1 } # 路由到 nginx_service_1
                - match: { prefix: "/" } # 匹配所有其他路径 (作为默认)
                  redirect: # 执行重定向
                    host_redirect: "www.hihihiai.com" # 重定向到 www.hihihiai.com (路径不变)
          http_filters:
          - name: envoy.filters.http.router # 最终的 HTTP 路由过滤器
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router

  clusters: # 上游服务集群定义
  - name: nginx_service_1 # 名为 nginx_service_1 的集群
    type: LOGICAL_DNS # 通过 DNS 发现服务 (如 Docker 服务名)
    load_assignment:
      cluster_name: nginx_service_1
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: nginx1 # 上游服务主机名 (如 Docker service 'nginx1')
                port_value: 80  # 上游服务端口

  - name: local_cluster # 名为 local_cluster 的集群
    type: STATIC # 静态配置上游主机地址
    load_assignment:
      cluster_name: local_cluster
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address: { address: 172.31.2.11, port_value: 80 } # 后端服务实例1
        - endpoint:
            address:
              socket_address: { address: 172.31.2.12, port_value: 80 } # 后端服务实例2
```

简单来说上面的 Envoy 配置实现了一个：

- 监听在 80 端口的 HTTP 代理。
- 能够根据请求的 `Host` 域名将流量导向不同的处理逻辑。
- 对于 `hihihiai.com` 域名，将所有请求代理到 `local_cluster`（一组静态IP的后端）。
- 对于 `test.com` 域名：
  - `/test.html` 路径的请求代理到 `nginx_service_1`（一个通过DNS发现的后端，可能是个 Docker 服务）。
  - 其他所有路径的请求则重定向到 `www.hihihiai.com`。

docker-compose.yaml:

```yaml
version: '3.8'

services:
  nginx1:
    image: nginx:latest
    container_name: nginx_server_1
    volumes:
      - ./nginx1:/usr/share/nginx/html:ro
    networks:
      envoy_network:
        ipv4_address: 172.20.0.10 # 为 nginx1 分配静态 IP
    # ports: # 不需要直接暴露 Nginx 端口，流量通过 Envoy
    #   - "8081:80"

  nginx2:
    image: nginx:latest
    container_name: nginx_server_2
    volumes:
      - ./nginx2:/usr/share/nginx/html:ro
    networks:
      envoy_network:
        ipv4_address: 172.20.0.11 # 为 nginx2 分配静态 IP
    # ports: # 不需要直接暴露 Nginx 端口，流量通过 Envoy
    #   - "8082:80"

  envoy:
    image: envoyproxy/envoy:v1.29-latest # 建议使用具体的版本标签
    container_name: envoy_proxy
    volumes:
      - ./envoy.yaml:/etc/envoy/envoy.yaml:ro
    ports:
      - "80:80" # Envoy 外部端口
      - "9901:9901" # Envoy admin 端口
    networks:
      - envoy_network # Envoy 也连接到这个网络
    depends_on:
      - nginx1
      - nginx2

networks:
  envoy_network:
    driver: bridge
    ipam: # IP Address Management
      driver: default
      config:
        - subnet: 172.20.0.0/16 # 定义网络的子网
          # gateway: 172.20.0.1 # 可以选择性地指定网关
```

nginx 文件：

```
(base) ➜  4-envoy基础示例 git:(main) ✗ cat nginx1/index.html
nginx1%
(base) ➜  4-envoy基础示例 git:(main) ✗ cat nginx1/test.html
nginx1%
(base) ➜  4-envoy基础示例 git:(main) ✗ cat nginx2/index.html
nginx2%
(base) ➜  4-envoy基础示例 git:(main) ✗ cat nginx2/test.html
nginx2%
```

然后启动后现状：

```
✗ sudo docker ps -a
CONTAINER ID   IMAGE                                             COMMAND                   CREATED          STATUS                   PORTS                                                   NAMES
b2e02adc8458   envoyproxy/envoy:v1.29-latest                     "/docker-entrypoint.…"   37 seconds ago   Up 37 seconds            0.0.0.0:80->80/tcp, 0.0.0.0:9901->9901/tcp, 10000/tcp   envoy_proxy
83c5048c7849   nginx:latest                                      "/docker-entrypoint.…"   37 seconds ago   Up 37 seconds            80/tcp                                                  nginx_server_2
d55060ccd8a4   nginx:latest                                      "/docker-entrypoint.…"   37 seconds ago   Up 37 seconds            80/tcp                                                  nginx_server_1
```

测试：

```
# 配置 hosts
$ vim /etc/hosts
127.0.0.1  www.hihihiai.com
127.0.0.1  hihihiai.com
127.0.0.1  test.com
```

访问 test.com 进行测试：

```
# test.com/test.html 指向 nginx1 
(base) ➜  ~ curl test.com/test.html
nginx1%
(base) ➜  ~ curl test.com/test.html
nginx1%
(base) ➜  ~ curl test.com/test.html
nginx1%


# test.com/index.html 重定向到 www.hihihiai.com/index.html 。
# 指向 nginx1 和 nginx2 
# -L： 这个选项告诉 curl 自动跟随HTTP重定向（比如301, 302）。
➜  ~ curl -i -L test.com/index.html
HTTP/1.1 301 Moved Permanently
location: http://www.hihihiai.com/index.html
date: Fri, 09 May 2025 14:07:07 GMT
server: envoy
content-length: 0

HTTP/1.1 200 OK
server: envoy
date: Fri, 09 May 2025 14:07:08 GMT
content-type: text/html
content-length: 6
last-modified: Fri, 09 May 2025 13:41:36 GMT
etag: "681e0610-6"
accept-ranges: bytes
x-envoy-upstream-service-time: 0

# 访问多次会访问到 nginx1 和 nginx2 
(base) ➜  ~ curl -L test.com/index.html
nginx1%
(base) ➜  ~ curl -L test.com/index.html
nginx1%
(base) ➜  ~ curl -L test.com/index.html
nginx2%
(base) ➜  ~ curl -L test.com/index.html
nginx1%
(base) ➜  ~ curl -L test.com/index.html
nginx2%
```

访问 hihihiai.com 进行测试：

```
(base) ➜  ~ curl hihihiai.com/test.html
nginx1%
(base) ➜  ~ curl hihihiai.com/test.html
nginx1%
(base) ➜  ~ curl hihihiai.com/test.html
nginx1%
(base) ➜  ~ curl hihihiai.com/test.html
nginx2%
(base) ➜  ~ curl hihihiai.com/test.html
nginx1%
(base) ➜  ~
(base) ➜  ~ curl hihihiai.com/index.html
nginx2%
(base) ➜  ~ curl hihihiai.com/index.html
nginx2%
(base) ➜  ~ curl hihihiai.com/index.html
nginx2%
(base) ➜  ~ curl hihihiai.com/index.html
nginx1%
(base) ➜  ~ curl hihihiai.com/index.html
nginx2%
(base) ➜  ~ curl hihihiai.com/index.html
nginx2%
```

# 四、总结

总而言之，Envoy 就是云原生时代的 Nginx。它不仅具备了传统反向代理的核心功能，更在此基础上拓展了诸多高级特性，其中最具革命性的当属其对 xDS API 协议簇的全面支持。

正是因为 xDS，Envoy 摆脱了传统代理软件静态配置、手动更新的桎梏。我们可以将其精髓通俗地理解为：**一个可以通过 API 动态下发配置、并实时热更新这些配置的“超级 Nginx”**。这种动态配置能力使得 Envoy 能够完美融入快速迭代、弹性伸缩的微服务架构和 Service Mesh（服务网格）体系中，成为连接、保护和观测现代应用流量的关键组件。所以，了解 Envoy 架构和作用，对于驾驭复杂的云原生环境至关重要。

