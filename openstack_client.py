"""
openstack_client.py - Module xác thực và gửi request tới OpenStack API
"""
import requests
import json
import config

# Tắt cảnh báo SSL nếu dùng self-signed cert
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


class OpenStackClient:
    """Client xác thực Keystone và gọi OpenStack REST API."""

    def __init__(self):
        self.token = None
        self.project_id = None
        self.endpoints = {
            "identity": config.IDENTITY_URL,
            "compute": config.COMPUTE_URL,
            "image": config.IMAGE_URL,
            "network": config.NETWORK_URL,
            "loadbalancer": config.LOADBALANCER_URL,
            "placement": config.PLACEMENT_URL,
            "volume": config.VOLUME_URL,
        }

    # -------------------------------------------------------
    # Authentication
    # -------------------------------------------------------
    def _identity_url(self):
        return self.endpoints["identity"].rstrip("/")

    def _project_scope(self):
        if getattr(config, "AUTH_PROJECT_ID", ""):
            return {"project": {"id": config.AUTH_PROJECT_ID}}
        return {
            "project": {
                "name": config.AUTH_PROJECT_NAME,
                "domain": {"name": config.AUTH_PROJECT_DOMAIN_NAME},
            }
        }

    def _password_auth_body(self):
        return {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": config.AUTH_USERNAME,
                            "domain": {"name": config.AUTH_USER_DOMAIN_NAME},
                            "password": config.AUTH_PASSWORD,
                        }
                    },
                },
                "scope": self._project_scope(),
            }
        }

    def _application_credential_auth_body(self):
        credential = {"secret": config.APP_CRED_SECRET}
        if getattr(config, "APP_CRED_ID", ""):
            credential["id"] = config.APP_CRED_ID
        else:
            credential["name"] = config.APP_CRED_NAME
            credential["user"] = {
                "name": config.AUTH_USERNAME,
                "domain": {"name": config.AUTH_USER_DOMAIN_NAME},
            }
        return {
            "auth": {
                "identity": {
                    "methods": ["application_credential"],
                    "application_credential": credential,
                }
            }
        }

    def _auth_error_message(self, resp, method):
        detail = ""
        try:
            payload = resp.json()
            detail = payload.get("error", {}).get("message", "")
        except ValueError:
            detail = resp.text.strip()

        hints = []
        if method == "password":
            hints.append("Kiểm tra AUTH_USERNAME, AUTH_PASSWORD và project scope.")
            hints.append("Nếu chuỗi bí mật bạn đang dùng là Application Credential Secret, đổi AUTH_METHOD thành 'application_credential'.")
            hints.append("Nếu trường cung cấp PROJECT_ID thay vì PROJECT_NAME, điền vào AUTH_PROJECT_ID.")
        else:
            hints.append("Kiểm tra APP_CRED_ID hoặc APP_CRED_NAME và APP_CRED_SECRET.")
            hints.append("Nếu dùng APP_CRED_NAME, cần đúng AUTH_USERNAME và AUTH_USER_DOMAIN_NAME.")

        joined_hints = " ".join(hints)
        return (
            f"Keystone auth failed with HTTP {resp.status_code} using method '{method}'. "
            f"{detail or 'No error detail returned.'} {joined_hints}"
        )

    def _authenticate_with_body(self, method, body):
        url = f"{self._identity_url()}/auth/tokens"
        resp = requests.post(url, json=body, verify=False)
        if not resp.ok:
            raise RuntimeError(self._auth_error_message(resp, method))
        self.token = resp.headers["X-Subject-Token"]
        data = resp.json()
        self.project_id = data.get("token", {}).get("project", {}).get("id")
        project_note = f" Project ID: {self.project_id}" if self.project_id else ""
        print(f"[OK] Xác thực thành công bằng {method}.{project_note}")
        return self.token

    def authenticate(self):
        """Xác thực với Keystone v3 và lấy token."""
        method = getattr(config, "AUTH_METHOD", "password").strip().lower()
        if method == "application_credential":
            return self._authenticate_with_body(method, self._application_credential_auth_body())
        if method == "password":
            return self._authenticate_with_body(method, self._password_auth_body())
        raise ValueError("AUTH_METHOD phải là 'password' hoặc 'application_credential'.")

    def _headers(self):
        return {
            "X-Auth-Token": self.token,
            "Content-Type": "application/json",
        }

    def _format_http_error(self, resp):
        detail = ""
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                err = payload.get("error", {})
                detail = err.get("message", "")

                if not detail:
                    neutron_error = payload.get("NeutronError", {})
                    detail = neutron_error.get("message", "")

                if not detail:
                    # Nova hay trả lỗi dưới các key như badRequest/forbidden/overLimit.
                    for key in [
                        "badRequest",
                        "forbidden",
                        "overLimit",
                        "itemNotFound",
                        "computeFault",
                        "conflictingRequest",
                    ]:
                        if key in payload and isinstance(payload[key], dict):
                            detail = payload[key].get("message", "")
                            if detail:
                                break

                if not detail:
                    # Fallback để không mất thông tin khi format lạ.
                    detail = json.dumps(payload, ensure_ascii=False)
        except ValueError:
            detail = resp.text.strip()
        if not detail:
            detail = "No error detail returned by API."
        return f"HTTP {resp.status_code} - {detail}"

    # -------------------------------------------------------
    # Generic HTTP helpers
    # -------------------------------------------------------
    def get(self, service, path, params=None):
        url = f"{self.endpoints[service]}{path}"
        resp = requests.get(url, headers=self._headers(), params=params, verify=False)
        if not resp.ok:
            raise RuntimeError(self._format_http_error(resp))
        return resp.json()

    def post(self, service, path, body=None):
        url = f"{self.endpoints[service]}{path}"
        resp = requests.post(url, headers=self._headers(), json=body, verify=False)
        if not resp.ok:
            raise RuntimeError(self._format_http_error(resp))
        return resp.json() if resp.text else {}

    def put(self, service, path, body=None):
        url = f"{self.endpoints[service]}{path}"
        resp = requests.put(url, headers=self._headers(), json=body, verify=False)
        if not resp.ok:
            raise RuntimeError(self._format_http_error(resp))
        return resp.json() if resp.text else {}

    def delete(self, service, path):
        url = f"{self.endpoints[service]}{path}"
        resp = requests.delete(url, headers=self._headers(), verify=False)
        if not resp.ok:
            raise RuntimeError(self._format_http_error(resp))
        return True

    # -------------------------------------------------------
    # 1. Flavors & Images
    # -------------------------------------------------------
    def list_flavors(self):
        data = self.get("compute", "/flavors/detail")
        return data.get("flavors", [])

    def list_images(self):
        data = self.get("image", "/v2/images")
        return data.get("images", [])

    # -------------------------------------------------------
    # 2. Networks & Subnets
    # -------------------------------------------------------
    def list_networks(self):
        data = self.get("network", "/v2.0/networks")
        return data.get("networks", [])

    def create_network(self, name, admin_state_up=True):
        body = {"network": {"name": name, "admin_state_up": admin_state_up}}
        data = self.post("network", "/v2.0/networks", body)
        return data.get("network", data)

    def delete_network(self, network_id):
        return self.delete("network", f"/v2.0/networks/{network_id}")

    def list_subnets(self):
        data = self.get("network", "/v2.0/subnets")
        return data.get("subnets", [])

    def create_subnet(self, network_id, name, cidr, ip_version=4,
                      gateway_ip=None, dns_nameservers=None):
        subnet = {
            "network_id": network_id,
            "name": name,
            "cidr": cidr,
            "ip_version": ip_version,
        }
        if gateway_ip:
            subnet["gateway_ip"] = gateway_ip
        if dns_nameservers:
            subnet["dns_nameservers"] = dns_nameservers
        body = {"subnet": subnet}
        data = self.post("network", "/v2.0/subnets", body)
        return data.get("subnet", data)

    def delete_subnet(self, subnet_id):
        return self.delete("network", f"/v2.0/subnets/{subnet_id}")

    # -------------------------------------------------------
    # 3. Routers
    # -------------------------------------------------------
    def list_routers(self):
        data = self.get("network", "/v2.0/routers")
        return data.get("routers", [])

    def create_router(self, name, external_network_id=None):
        router = {"name": name, "admin_state_up": True}
        if external_network_id:
            router["external_gateway_info"] = {"network_id": external_network_id}
        body = {"router": router}
        data = self.post("network", "/v2.0/routers", body)
        return data.get("router", data)

    def delete_router(self, router_id):
        return self.delete("network", f"/v2.0/routers/{router_id}")

    def clear_router_gateway(self, router_id):
        body = {"router": {"external_gateway_info": None}}
        data = self.put("network", f"/v2.0/routers/{router_id}", body)
        return data.get("router", data)

    def set_router_gateway(self, router_id, external_network_id):
        body = {
            "router": {
                "external_gateway_info": {
                    "network_id": external_network_id,
                }
            }
        }
        data = self.put("network", f"/v2.0/routers/{router_id}", body)
        return data.get("router", data)

    def add_router_interface(self, router_id, subnet_id):
        body = {"subnet_id": subnet_id}
        return self.put("network", f"/v2.0/routers/{router_id}/add_router_interface", body)

    def remove_router_interface(self, router_id, subnet_id):
        body = {"subnet_id": subnet_id}
        return self.put("network", f"/v2.0/routers/{router_id}/remove_router_interface", body)

    # -------------------------------------------------------
    # 4. Instances (Servers)
    # -------------------------------------------------------
    def list_servers(self):
        data = self.get("compute", "/servers/detail")
        return data.get("servers", [])

    def create_server(self, name, image_id, flavor_id, network_id,
                      security_groups=None, user_data=None, key_name=None,
                      boot_from_volume=False, volume_size=None,
                      delete_on_termination=True):
        server = {
            "name": name,
            "flavorRef": flavor_id,
            "networks": [{"uuid": network_id}],
        }
        if boot_from_volume:
            if not volume_size:
                raise ValueError("volume_size là bắt buộc khi boot_from_volume=True")
            server["block_device_mapping_v2"] = [{
                "boot_index": 0,
                "uuid": image_id,
                "source_type": "image",
                "destination_type": "volume",
                "volume_size": int(volume_size),
                "delete_on_termination": bool(delete_on_termination),
            }]
        else:
            server["imageRef"] = image_id
        if security_groups:
            server["security_groups"] = [{"name": sg} for sg in security_groups]
        if user_data:
            import base64
            server["user_data"] = base64.b64encode(user_data.encode()).decode()
        if key_name:
            server["key_name"] = key_name
        body = {"server": server}
        data = self.post("compute", "/servers", body)
        return data.get("server", data)

    def delete_server(self, server_id):
        return self.delete("compute", f"/servers/{server_id}")

    def get_server(self, server_id):
        data = self.get("compute", f"/servers/{server_id}")
        return data.get("server", data)

    def wait_server_active(self, server_id, timeout=300, interval=5):
        """Đợi server chuyển sang trạng thái ACTIVE."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            srv = self.get_server(server_id)
            status = srv.get("status", "UNKNOWN")
            print(f"  Server status: {status}")
            if status == "ACTIVE":
                return srv
            if status == "ERROR":
                raise RuntimeError(f"Server {server_id} lỗi!")
            time.sleep(interval)
        raise TimeoutError(f"Server {server_id} không ACTIVE sau {timeout}s")

    # -------------------------------------------------------
    # 5. Security Groups
    # -------------------------------------------------------
    def list_security_groups(self):
        data = self.get("network", "/v2.0/security-groups")
        return data.get("security_groups", [])

    def create_security_group(self, name, description=""):
        body = {"security_group": {"name": name, "description": description}}
        data = self.post("network", "/v2.0/security-groups", body)
        return data.get("security_group", data)

    def create_security_group_rule(self, sg_id, direction, protocol,
                                   port_range_min=None, port_range_max=None,
                                   remote_ip_prefix="0.0.0.0/0", ethertype="IPv4"):
        rule = {
            "security_group_id": sg_id,
            "direction": direction,
            "protocol": protocol,
            "ethertype": ethertype,
            "remote_ip_prefix": remote_ip_prefix,
        }
        if port_range_min is not None:
            rule["port_range_min"] = port_range_min
        if port_range_max is not None:
            rule["port_range_max"] = port_range_max
        body = {"security_group_rule": rule}
        data = self.post("network", "/v2.0/security-group-rules", body)
        return data.get("security_group_rule", data)

    # -------------------------------------------------------
    # 6. Floating IPs
    # -------------------------------------------------------
    def list_floating_ips(self, floating_network_id=None):
        params = {}
        if floating_network_id:
            params["floating_network_id"] = floating_network_id
        data = self.get("network", "/v2.0/floatingips", params=params)
        return data.get("floatingips", [])

    def create_floating_ip(self, external_network_id):
        body = {"floatingip": {"floating_network_id": external_network_id}}
        data = self.post("network", "/v2.0/floatingips", body)
        return data.get("floatingip", data)

    def associate_floating_ip(self, floatingip_id, port_id):
        body = {"floatingip": {"port_id": port_id}}
        url = f"{self.endpoints['network']}/v2.0/floatingips/{floatingip_id}"
        resp = requests.put(url, headers=self._headers(), json=body, verify=False)
        if not resp.ok:
            raise RuntimeError(self._format_http_error(resp))
        return resp.json().get("floatingip", resp.json())

    def delete_floating_ip(self, floatingip_id):
        return self.delete("network", f"/v2.0/floatingips/{floatingip_id}")

    # -------------------------------------------------------
    # 7. Ports
    # -------------------------------------------------------
    def list_ports(self, device_id=None):
        params = {}
        if device_id:
            params["device_id"] = device_id
        data = self.get("network", "/v2.0/ports", params=params)
        return data.get("ports", [])

    # -------------------------------------------------------
    # 8. Load Balancer (Octavia)
    # -------------------------------------------------------
    def list_loadbalancers(self):
        data = self.get("loadbalancer", "/v2/lbaas/loadbalancers")
        return data.get("loadbalancers", [])

    def create_loadbalancer(self, name, subnet_id, description=""):
        body = {
            "loadbalancer": {
                "name": name,
                "vip_subnet_id": subnet_id,
                "description": description,
                "admin_state_up": True,
            }
        }
        data = self.post("loadbalancer", "/v2/lbaas/loadbalancers", body)
        return data.get("loadbalancer", data)

    def get_loadbalancer(self, lb_id):
        data = self.get("loadbalancer", f"/v2/lbaas/loadbalancers/{lb_id}")
        return data.get("loadbalancer", data)

    def delete_loadbalancer(self, lb_id, cascade=True):
        path = f"/v2/lbaas/loadbalancers/{lb_id}"
        if cascade:
            path += "?cascade=true"
        return self.delete("loadbalancer", path)

    def wait_lb_active(self, lb_id, timeout=300, interval=5):
        import time
        start = time.time()
        while time.time() - start < timeout:
            lb = self.get_loadbalancer(lb_id)
            status = lb.get("provisioning_status", "UNKNOWN")
            print(f"  LB status: {status}")
            if status == "ACTIVE":
                return lb
            if status == "ERROR":
                raise RuntimeError(f"LB {lb_id} lỗi!")
            time.sleep(interval)
        raise TimeoutError(f"LB {lb_id} không ACTIVE sau {timeout}s")

    def create_listener(self, lb_id, name, protocol, port):
        body = {
            "listener": {
                "loadbalancer_id": lb_id,
                "name": name,
                "protocol": protocol,
                "protocol_port": port,
                "admin_state_up": True,
            }
        }
        data = self.post("loadbalancer", "/v2/lbaas/listeners", body)
        return data.get("listener", data)

    def list_listeners(self):
        data = self.get("loadbalancer", "/v2/lbaas/listeners")
        return data.get("listeners", [])

    def create_pool(self, listener_id, name, protocol, lb_algorithm="ROUND_ROBIN"):
        body = {
            "pool": {
                "listener_id": listener_id,
                "name": name,
                "protocol": protocol,
                "lb_algorithm": lb_algorithm,
                "admin_state_up": True,
            }
        }
        data = self.post("loadbalancer", "/v2/lbaas/pools", body)
        return data.get("pool", data)

    def list_pools(self):
        data = self.get("loadbalancer", "/v2/lbaas/pools")
        return data.get("pools", [])

    def create_member(self, pool_id, name, address, port, subnet_id):
        body = {
            "member": {
                "name": name,
                "address": address,
                "protocol_port": port,
                "subnet_id": subnet_id,
                "admin_state_up": True,
            }
        }
        data = self.post("loadbalancer", f"/v2/lbaas/pools/{pool_id}/members", body)
        return data.get("member", data)

    def list_members(self, pool_id):
        data = self.get("loadbalancer", f"/v2/lbaas/pools/{pool_id}/members")
        return data.get("members", [])

    def delete_member(self, pool_id, member_id):
        return self.delete("loadbalancer", f"/v2/lbaas/pools/{pool_id}/members/{member_id}")

    def create_healthmonitor(self, pool_id, hm_type="HTTP", delay=5,
                              timeout=5, max_retries=3, url_path="/"):
        body = {
            "healthmonitor": {
                "pool_id": pool_id,
                "type": hm_type,
                "delay": delay,
                "timeout": timeout,
                "max_retries": max_retries,
                "url_path": url_path,
                "http_method": "GET",
                "expected_codes": "200",
                "admin_state_up": True,
            }
        }
        data = self.post("loadbalancer", "/v2/lbaas/healthmonitors", body)
        return data.get("healthmonitor", data)

    # -------------------------------------------------------
    # Helper: find external network
    # -------------------------------------------------------
    def find_external_network(self):
        nets = self.list_networks()
        for n in nets:
            if n.get("router:external") or n.get("name") == config.EXTERNAL_NETWORK_NAME:
                return n
        return None
