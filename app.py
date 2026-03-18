"""
===================================================================
 OpenStack Resource Manager - NT533 Lab 2
 Ứng dụng quản lý tài nguyên OpenStack qua REST API
===================================================================
"""
import sys
import json
import time
import config
from openstack_client import OpenStackClient

client = OpenStackClient()

# ============================================================
# Utility
# ============================================================

def print_table(headers, rows):
    """In bảng đẹp ra console."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)
    sep = "-+-".join("-" * w for w in col_widths)
    print(fmt.format(*headers))
    print(sep)
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


def pause():
    input("\nNhấn Enter để tiếp tục...")


def ask(prompt, default=""):
    val = input(f"{prompt} [{default}]: ").strip()
    return val if val else default


def choose_from_list(items, name_key="name", id_key="id", label=""):
    """Cho phép người dùng chọn 1 item từ danh sách."""
    if not items:
        print(f"  Không có {label} nào.")
        return None
    for i, item in enumerate(items):
        print(f"  {i+1}. {item.get(name_key, 'N/A')} ({item.get(id_key, '')})")
    while True:
        choice = input(f"Chọn {label} (1-{len(items)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            return items[int(choice) - 1]
        print("  Lựa chọn không hợp lệ!")


def get_router_using_subnet(subnet_id):
    """Trả về router đang gắn interface với subnet, nếu có."""
    ports = client.list_ports()
    for p in ports:
        owner = (p.get("device_owner") or "").lower()
        if "router_interface" not in owner:
            continue
        for fixed in p.get("fixed_ips", []):
            if fixed.get("subnet_id") == subnet_id:
                return {
                    "router_id": p.get("device_id"),
                    "port_id": p.get("id"),
                    "ip_address": fixed.get("ip_address"),
                }
    return None


def list_attachable_subnets():
    """Danh sách subnet nội bộ thuộc project hiện tại để gắn router interface."""
    networks = client.list_networks()
    project_id = client.project_id

    network_map = {n.get("id"): n for n in networks}
    for n in networks:
        if n.get("router:external"):
            network_map.pop(n.get("id"), None)

    subnets = client.list_subnets()
    result = []
    for s in subnets:
        net = network_map.get(s.get("network_id"))
        if not net:
            continue
        subnet_owner = s.get("project_id") or s.get("tenant_id")
        net_owner = net.get("project_id") or net.get("tenant_id")
        if project_id and subnet_owner != project_id and net_owner != project_id:
            continue
        result.append(s)
    return result


def validate_flavor_image_compat(flavor, image):
    """Kiểm tra flavor có đáp ứng min_disk/min_ram của image hay không."""
    flavor_disk = int(flavor.get("disk") or 0)
    flavor_ram = int(flavor.get("ram") or 0)
    min_disk = int(image.get("min_disk") or 0)
    min_ram = int(image.get("min_ram") or 0)

    errors = []
    if flavor_disk > 0 and flavor_disk < min_disk:
        errors.append(
            f"Disk của flavor ({flavor_disk} GB) nhỏ hơn min_disk của image ({min_disk} GB)."
        )
    if flavor_ram < min_ram:
        errors.append(
            f"RAM của flavor ({flavor_ram} MB) nhỏ hơn min_ram của image ({min_ram} MB)."
        )

    if errors:
        raise ValueError(" ".join(errors))


def resolve_boot_options(flavor, image, interactive=True):
    """Xác định cách boot phù hợp theo flavor/image."""
    flavor_disk = int(flavor.get("disk") or 0)
    min_disk = int(image.get("min_disk") or 0)

    if flavor_disk > 0:
        return {"boot_from_volume": False, "volume_size": None}

    default_size = max(min_disk, 10)
    volume_size = default_size
    if interactive:
        chosen = ask(
            "Flavor disk=0 -> sẽ boot từ volume. Kích thước volume (GB)",
            str(default_size),
        )
        try:
            volume_size = int(chosen)
        except ValueError:
            raise ValueError("Kích thước volume phải là số nguyên dương.")

    if volume_size < max(1, min_disk):
        raise ValueError(f"Volume size phải >= {max(1, min_disk)} GB cho image đã chọn.")

    return {"boot_from_volume": True, "volume_size": volume_size}


def pick_compatible_flavor(image):
    """Chỉ cho chọn flavor hợp lệ với image hiện tại."""
    flavors = client.list_flavors()
    valid_flavors = []
    blocked = []

    for f in flavors:
        try:
            validate_flavor_image_compat(f, image)
            valid_flavors.append(f)
        except ValueError as e:
            blocked.append((f, str(e)))

    if not valid_flavors:
        raise ValueError("Không có flavor hợp lệ cho image này. Hãy chọn image khác.")

    print("\n-- Chọn Flavor (tương thích với image đã chọn) --")
    for i, f in enumerate(valid_flavors):
        print(
            f"  {i+1}. {f.get('name', 'N/A')} "
            f"({f.get('id', '')}) - vCPU: {f.get('vcpus', 0)}, "
            f"RAM: {f.get('ram', 0)} MB, Disk: {f.get('disk', 0)} GB"
        )

    if blocked:
        print("\n  Flavor không hợp lệ đã ẩn:")
        for f, reason in blocked:
            print(f"  - {f.get('name', 'N/A')}: {reason}")

    while True:
        choice = input(f"Chọn flavor (1-{len(valid_flavors)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(valid_flavors):
            return valid_flavors[int(choice) - 1]
        print("  Lựa chọn không hợp lệ!")


def generate_userdata_script():
    """Tạo cloud-init script cài đặt web server hiển thị thông tin nhóm."""
    return f"""#!/bin/bash
set -e

# Cài đặt nginx
apt-get update -y
apt-get install -y nginx curl

# Lấy IP của máy ảo
VM_IP=$(hostname -I | awk '{{print $1}}')

# Tạo trang web hiển thị thông tin nhóm
cat > /var/www/html/index.html <<HTMLEOF
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NT533 - {config.GROUP_NAME}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
        }}
        .card {{
            background: white; border-radius: 16px; padding: 40px 50px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3); text-align: center;
            max-width: 500px; width: 90%;
        }}
        h1 {{ color: #4a3f8a; margin-bottom: 5px; }}
        h2 {{ color: #667eea; font-weight: 400; }}
        .info {{ background: #f0f0ff; padding: 15px; border-radius: 8px; margin: 15px 0; }}
        .ip {{ font-size: 1.4em; color: #e74c3c; font-weight: bold; }}
        .footer {{ color: #888; font-size: 0.85em; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{config.GROUP_NAME}</h1>
        <h2>NT533 - Hệ tính toán phân bố</h2>
        <div class="info">
            <p><strong>Thành viên:</strong> {config.GROUP_MEMBERS}</p>
            <p><strong>GVHD:</strong> baonv@uit.edu.vn</p>
        </div>
        <p>Địa chỉ IP máy ảo:</p>
        <p class="ip">$VM_IP</p>
        <p>Hostname: $(hostname)</p>
        <div class="footer">
            Powered by OpenStack &bull; UIT Cloud<br>
            Server Time: $(date '+%Y-%m-%d %H:%M:%S')
        </div>
    </div>
</body>
</html>
HTMLEOF

# Khởi động nginx
systemctl enable nginx
systemctl restart nginx
echo "Web server configured successfully!"
"""


# ============================================================
# Menu Handlers
# ============================================================

# ----- 1. Liệt kê Flavors & Images -----
def menu_list_flavors():
    print("\n=== DANH SÁCH FLAVORS ===")
    flavors = client.list_flavors()
    rows = []
    for f in flavors:
        rows.append([
            f.get("id", ""),
            f.get("name", ""),
            f.get("vcpus", ""),
            f"{f.get('ram', 0)} MB",
            f"{f.get('disk', 0)} GB",
        ])
    print_table(["ID", "Name", "vCPUs", "RAM", "Disk"], rows)
    print(f"\nTổng: {len(flavors)} flavor(s)")


def menu_list_images():
    print("\n=== DANH SÁCH IMAGES ===")
    images = client.list_images()
    rows = []
    for img in images:
        size_mb = (img.get("size") or 0) / (1024 * 1024)
        rows.append([
            img.get("id", ""),
            img.get("name", ""),
            img.get("status", ""),
            f"{size_mb:.1f} MB",
            img.get("disk_format", ""),
        ])
    print_table(["ID", "Name", "Status", "Size", "Format"], rows)
    print(f"\nTổng: {len(images)} image(s)")


# ----- 2. Networks & Subnets -----
def menu_list_networks():
    print("\n=== DANH SÁCH NETWORKS ===")
    nets = client.list_networks()
    rows = []
    for n in nets:
        rows.append([
            n.get("id", ""),
            n.get("name", ""),
            n.get("status", ""),
            "Yes" if n.get("router:external") else "No",
            ", ".join(n.get("subnets", [])),
        ])
    print_table(["ID", "Name", "Status", "External", "Subnets"], rows)
    print(f"\nTổng: {len(nets)} network(s)")


def menu_create_network():
    print("\n=== TẠO NETWORK ===")
    name = ask("Tên network", f"{config.GROUP_NAME}_net")
    net = client.create_network(name)
    print(f"[OK] Đã tạo network: {net['name']} (ID: {net['id']})")

    create_sub = ask("Tạo subnet cho network này? (y/n)", "y")
    if create_sub.lower() == "y":
        sub_name = ask("Tên subnet", f"{config.GROUP_NAME}_subnet")
        cidr = ask("CIDR", "192.168.1.0/24")
        gw = ask("Gateway IP", "192.168.1.1")
        dns = ask("DNS nameservers (cách nhau bởi dấu phẩy)", "8.8.8.8,8.8.4.4")
        dns_list = [d.strip() for d in dns.split(",")]
        subnet = client.create_subnet(net["id"], sub_name, cidr,
                                       gateway_ip=gw, dns_nameservers=dns_list)
        print(f"[OK] Đã tạo subnet: {subnet['name']} (ID: {subnet['id']})")
    return net


def menu_delete_network():
    print("\n=== XÓA NETWORK ===")
    nets = client.list_networks()
    user_nets = [n for n in nets if not n.get("router:external")]
    net = choose_from_list(user_nets, label="network cần xóa")
    if net:
        confirm = ask(f"Xác nhận xóa network '{net['name']}'? (y/n)", "n")
        if confirm.lower() == "y":
            client.delete_network(net["id"])
            print(f"[OK] Đã xóa network: {net['name']}")


def menu_list_subnets():
    print("\n=== DANH SÁCH SUBNETS ===")
    subnets = client.list_subnets()
    rows = []
    for s in subnets:
        rows.append([
            s.get("id", ""),
            s.get("name", ""),
            s.get("cidr", ""),
            s.get("gateway_ip", ""),
            s.get("network_id", "")[:12] + "...",
        ])
    print_table(["ID", "Name", "CIDR", "Gateway", "Network ID"], rows)
    print(f"\nTổng: {len(subnets)} subnet(s)")


def menu_create_subnet():
    print("\n=== TẠO SUBNET ===")
    nets = client.list_networks()
    user_nets = [n for n in nets if not n.get("router:external")]
    net = choose_from_list(user_nets, label="network")
    if not net:
        return
    name = ask("Tên subnet", f"{config.GROUP_NAME}_subnet")
    cidr = ask("CIDR", "192.168.1.0/24")
    gw = ask("Gateway IP", "192.168.1.1")
    dns = ask("DNS nameservers", "8.8.8.8,8.8.4.4")

    # Tránh gửi request tạo subnet trùng trong cùng network.
    existing_subnets = [s for s in client.list_subnets() if s.get("network_id") == net["id"]]
    for s in existing_subnets:
        if s.get("name") == name:
            raise ValueError(
                f"Subnet name '{name}' đã tồn tại trong network '{net.get('name')}'. "
                f"Vui lòng dùng tên khác."
            )
        if s.get("cidr") == cidr:
            raise ValueError(
                f"CIDR '{cidr}' đã tồn tại trong network '{net.get('name')}' "
                f"(subnet hiện có: {s.get('name')})."
            )

    dns_list = [d.strip() for d in dns.split(",")]
    subnet = client.create_subnet(net["id"], name, cidr,
                                   gateway_ip=gw, dns_nameservers=dns_list)
    print(f"[OK] Đã tạo subnet: {subnet['name']} (ID: {subnet['id']})")


def menu_delete_subnet():
    print("\n=== XÓA SUBNET ===")
    subnets = client.list_subnets()
    sub = choose_from_list(subnets, label="subnet cần xóa")
    if sub:
        confirm = ask(f"Xác nhận xóa subnet '{sub['name']}'? (y/n)", "n")
        if confirm.lower() == "y":
            client.delete_subnet(sub["id"])
            print(f"[OK] Đã xóa subnet: {sub['name']}")


# ----- 3. Routers -----
def menu_list_routers():
    print("\n=== DANH SÁCH ROUTERS ===")
    routers = client.list_routers()
    rows = []
    for r in routers:
        gw = r.get("external_gateway_info")
        ext_net = gw.get("network_id", "")[:12] + "..." if gw else "None"
        rows.append([
            r.get("id", ""),
            r.get("name", ""),
            r.get("status", ""),
            ext_net,
        ])
    print_table(["ID", "Name", "Status", "External Gateway"], rows)
    print(f"\nTổng: {len(routers)} router(s)")


def menu_create_router():
    print("\n=== TẠO ROUTER ===")
    name = ask("Tên router", f"{config.GROUP_NAME}_router")
    ext_net = client.find_external_network()
    ext_id = None
    if ext_net:
        use_ext = ask(f"Kết nối tới external network '{ext_net['name']}'? (y/n)", "y")
        if use_ext.lower() == "y":
            ext_id = ext_net["id"]
    router = client.create_router(name, ext_id)
    print(f"[OK] Đã tạo router: {router['name']} (ID: {router['id']})")

    add_if = ask("Thêm interface tới subnet? (y/n)", "y")
    if add_if.lower() == "y":
        subnets = list_attachable_subnets()
        sub = choose_from_list(subnets, label="subnet")
        if sub:
            bound = get_router_using_subnet(sub["id"])
            if bound:
                raise ValueError(
                    f"Subnet '{sub.get('name')}' đã được gắn với router {bound['router_id']} "
                    f"(IP interface: {bound.get('ip_address', 'N/A')}). "
                    f"Hãy gỡ interface ở router cũ trước khi gắn vào router mới."
                )
            try:
                client.add_router_interface(router["id"], sub["id"])
            except Exception as e:
                msg = str(e)
                if "already allocated in subnet" in msg:
                    raise ValueError(
                        f"Subnet '{sub.get('name')}' đã có gateway/interface của router khác. "
                        f"Hãy gỡ interface subnet này khỏi router cũ trước."
                    )
                if "not owned by project" in msg:
                    raise ValueError(
                        f"Subnet '{sub.get('name')}' không thuộc project hiện tại, "
                        f"không thể gắn vào router của bạn."
                    )
                raise
            print(f"[OK] Đã thêm interface tới subnet: {sub['name']}")
    return router


def menu_delete_router():
    print("\n=== XÓA ROUTER ===")
    routers = client.list_routers()
    router = choose_from_list(routers, label="router cần xóa")
    if router:
        confirm = ask(f"Xác nhận xóa router '{router['name']}'? (y/n)", "n")
        if confirm.lower() == "y":
            # Xóa interfaces trước
            ports = client.list_ports(device_id=router["id"])
            for p in ports:
                if p.get("device_owner") == "network:router_interface":
                    for fixed in p.get("fixed_ips", []):
                        try:
                            client.remove_router_interface(router["id"], fixed["subnet_id"])
                            print(f"  Đã gỡ interface subnet {fixed['subnet_id']}")
                        except Exception:
                            pass

            # Gỡ external gateway trước khi xóa router.
            gateway = router.get("external_gateway_info") or {}
            ext_net_id = gateway.get("network_id")
            if ext_net_id:
                try:
                    client.clear_router_gateway(router["id"])
                    print("  Đã gỡ external gateway khỏi router")
                except Exception as e:
                    msg = str(e)
                    if "required by one or more floating IPs" in msg:
                        fips = client.list_floating_ips(floating_network_id=ext_net_id)
                        if not fips:
                            raise

                        print("  Router đang bị ràng buộc bởi Floating IP:")
                        for f in fips:
                            print(f"    - {f.get('floating_ip_address')} (id: {f.get('id')})")

                        drop_fips = ask("  Xóa các Floating IP này để tiếp tục xóa router? (y/n)", "n")
                        if drop_fips.lower() != "y":
                            raise ValueError("Đã hủy xóa router vì còn Floating IP phụ thuộc.")

                        for f in fips:
                            client.delete_floating_ip(f["id"])
                            print(f"  Đã xóa Floating IP: {f.get('floating_ip_address')}")

                        client.clear_router_gateway(router["id"])
                        print("  Đã gỡ external gateway sau khi xóa Floating IP")
                    else:
                        raise

            client.delete_router(router["id"])
            print(f"[OK] Đã xóa router: {router['name']}")


# ----- 4. Instances (Servers) -----
def menu_list_servers():
    print("\n=== DANH SÁCH MÁY ẢO ===")
    servers = client.list_servers()
    rows = []
    for s in servers:
        addrs = []
        for net_name, ips in s.get("addresses", {}).items():
            for ip in ips:
                label = f"{ip['addr']}"
                if ip.get("OS-EXT-IPS:type") == "floating":
                    label += " (floating)"
                addrs.append(label)
        rows.append([
            s.get("id", ""),
            s.get("name", ""),
            s.get("status", ""),
            ", ".join(addrs) if addrs else "N/A",
        ])
    print_table(["ID", "Name", "Status", "IP Addresses"], rows)
    print(f"\nTổng: {len(servers)} server(s)")


def menu_create_server():
    print("\n=== TẠO MÁY ẢO ===")
    name = ask("Tên máy ảo", f"{config.GROUP_NAME}_vm1")

    # Chọn image
    print("\n-- Chọn Image --")
    images = client.list_images()
    image = choose_from_list(images, label="image")
    if not image:
        return

    flavor = pick_compatible_flavor(image)

    # Chọn network
    print("\n-- Chọn Network --")
    nets = client.list_networks()
    user_nets = [n for n in nets if not n.get("router:external")]
    net = choose_from_list(user_nets, label="network")
    if not net:
        return

    # User data
    use_ud = ask("Sử dụng user data (cài web server tự động)? (y/n)", "y")
    user_data = generate_userdata_script() if use_ud.lower() == "y" else None
    boot_opts = resolve_boot_options(flavor, image, interactive=True)

    print(f"\nĐang tạo máy ảo '{name}'...")
    server = client.create_server(name, image["id"], flavor["id"], net["id"],
                                   user_data=user_data,
                                   boot_from_volume=boot_opts["boot_from_volume"],
                                   volume_size=boot_opts["volume_size"])
    print(f"[OK] Đã tạo máy ảo: {server['id']}")

    wait = ask("Đợi máy ảo ACTIVE? (y/n)", "y")
    if wait.lower() == "y":
        srv = client.wait_server_active(server["id"])
        print(f"[OK] Máy ảo đã ACTIVE!")

    # Floating IP
    assign_fip = ask("Gán Floating IP? (y/n)", "y")
    if assign_fip.lower() == "y":
        _assign_floating_ip(server["id"])

    return server


def _assign_floating_ip(server_id):
    """Gán Floating IP cho server."""
    # Tìm port của server và các subnet private mà VM đang dùng.
    ports = client.list_ports(device_id=server_id)
    if not ports:
        print("[LỖI] Không tìm thấy port của server!")
        return
    port_id = ports[0]["id"]
    server_subnet_ids = {
        fixed.get("subnet_id")
        for p in ports
        for fixed in p.get("fixed_ips", [])
        if fixed.get("subnet_id")
    }

    # Chỉ chọn external network thật sự reachable từ subnet của VM qua router.
    reachable_ext_net_id = None
    routers = client.list_routers()
    for r in routers:
        gw = r.get("external_gateway_info") or {}
        ext_id = gw.get("network_id")
        if not ext_id:
            continue

        r_ports = client.list_ports(device_id=r["id"])
        router_subnet_ids = {
            fixed.get("subnet_id")
            for rp in r_ports
            if "router_interface" in (rp.get("device_owner") or "")
            for fixed in rp.get("fixed_ips", [])
            if fixed.get("subnet_id")
        }
        if server_subnet_ids.intersection(router_subnet_ids):
            reachable_ext_net_id = ext_id
            break

    if not reachable_ext_net_id:
        raise ValueError(
            "Không tìm thấy router nối subnet của VM ra external network. "
            "Vui lòng cấu hình router: external gateway + interface vào subnet VM trước khi gán Floating IP."
        )

    networks = client.list_networks()
    ext_net = next((n for n in networks if n.get("id") == reachable_ext_net_id), None)
    ext_net_name = ext_net.get("name") if ext_net else reachable_ext_net_id

    # Tạo floating IP trên external network reachable.
    fip = client.create_floating_ip(reachable_ext_net_id)
    print(f"  Đã tạo Floating IP: {fip['floating_ip_address']} ({ext_net_name})")

    # Gắn vào port; nếu fail thì dọn rác floating ip vừa tạo.
    try:
        client.associate_floating_ip(fip["id"], port_id)
    except Exception:
        try:
            client.delete_floating_ip(fip["id"])
            print(f"  Đã thu hồi Floating IP lỗi: {fip['floating_ip_address']}")
        except Exception:
            pass
        raise

    print(f"[OK] Đã gán Floating IP {fip['floating_ip_address']} cho server {server_id}")
    return fip


def menu_delete_server():
    print("\n=== XÓA MÁY ẢO ===")
    servers = client.list_servers()
    srv = choose_from_list(servers, label="máy ảo cần xóa")
    if srv:
        confirm = ask(f"Xác nhận xóa máy ảo '{srv['name']}'? (y/n)", "n")
        if confirm.lower() == "y":
            # Xóa floating IP liên quan
            fips = client.list_floating_ips()
            ports = client.list_ports(device_id=srv["id"])
            port_ids = {p["id"] for p in ports}
            for fip in fips:
                if fip.get("port_id") in port_ids:
                    client.delete_floating_ip(fip["id"])
                    print(f"  Đã xóa Floating IP: {fip['floating_ip_address']}")
            client.delete_server(srv["id"])
            print(f"[OK] Đã xóa máy ảo: {srv['name']}")


# ----- 5 & 6. Thiết lập mạng + Tạo máy ảo hoàn chỉnh -----
def menu_full_setup():
    print("\n" + "=" * 60)
    print("  THIẾT LẬP MÔ HÌNH MẠNG + MÁY ẢO HOÀN CHỈNH")
    print("=" * 60)
    print("""
Quy trình:
  1. Tạo Network + Subnet
  2. Tạo Router (kết nối External + Internal)
  3. Tạo Security Group (cho phép SSH, HTTP, ICMP)
  4. Tạo máy ảo với user data (web server)
  5. Gán Floating IP
""")
    confirm = ask("Bắt đầu thiết lập? (y/n)", "y")
    if confirm.lower() != "y":
        return

    group = config.GROUP_NAME

    # --- 1. Network & Subnet ---
    print("\n[1/5] Tạo Network & Subnet...")
    net_name = ask("Tên network", f"{group}_net")
    sub_name = ask("Tên subnet", f"{group}_subnet")
    cidr = ask("CIDR", "192.168.1.0/24")
    gw = ask("Gateway", "192.168.1.1")

    network = client.create_network(net_name)
    print(f"  Network: {network['name']} ({network['id']})")

    subnet = client.create_subnet(
        network["id"], sub_name, cidr,
        gateway_ip=gw,
        dns_nameservers=["8.8.8.8", "8.8.4.4"]
    )
    print(f"  Subnet: {subnet['name']} ({subnet['id']})")

    # --- 2. Router ---
    print("\n[2/5] Tạo Router...")
    ext_net = client.find_external_network()
    if not ext_net:
        print("[LỖI] Không tìm thấy external network!")
        return
    router_name = ask("Tên router", f"{group}_router")
    router = client.create_router(router_name, ext_net["id"])
    print(f"  Router: {router['name']} ({router['id']})")
    print(f"  External gateway: {ext_net['name']}")

    # Thêm interface nối tới internal subnet
    bound = get_router_using_subnet(subnet["id"])
    if bound:
        raise ValueError(
            f"Subnet '{subnet.get('name')}' đã gắn với router {bound['router_id']} "
            f"(IP interface: {bound.get('ip_address', 'N/A')})."
        )
    client.add_router_interface(router["id"], subnet["id"])
    print(f"  Đã kết nối router tới subnet: {subnet['name']}")

    # --- 3. Security Group ---
    print("\n[3/5] Tạo Security Group...")
    sg_name = ask("Tên Security Group", f"{group}_sg")
    sg = client.create_security_group(sg_name, "Security group cho nhom")
    sg_id = sg["id"]
    print(f"  Security Group: {sg['name']} ({sg_id})")

    # Rules: SSH, HTTP, HTTPS, ICMP
    rules = [
        ("ingress", "tcp", 22, 22, "SSH"),
        ("ingress", "tcp", 80, 80, "HTTP"),
        ("ingress", "tcp", 443, 443, "HTTPS"),
        ("ingress", "icmp", None, None, "ICMP"),
    ]
    for direction, proto, pmin, pmax, desc in rules:
        client.create_security_group_rule(sg_id, direction, proto, pmin, pmax)
        print(f"  Rule: {desc} ({proto} {pmin or 'all'}-{pmax or 'all'})")

    # --- 4. Tạo máy ảo ---
    print("\n[4/5] Tạo máy ảo...")
    vm_name = ask("Tên máy ảo", f"{group}_vm1")

    print("  Chọn Image:")
    images = client.list_images()
    image = choose_from_list(images, label="image")
    if not image:
        return

    flavor = pick_compatible_flavor(image)
    boot_opts = resolve_boot_options(flavor, image, interactive=True)

    user_data = generate_userdata_script()
    server = client.create_server(
        vm_name, image["id"], flavor["id"], network["id"],
        security_groups=[sg_name],
        user_data=user_data,
        boot_from_volume=boot_opts["boot_from_volume"],
        volume_size=boot_opts["volume_size"],
    )
    print(f"  Máy ảo: {server['id']}")
    print("  Đang đợi máy ảo ACTIVE...")
    srv = client.wait_server_active(server["id"])
    print(f"  [OK] Máy ảo đã ACTIVE!")

    # --- 5. Floating IP ---
    print("\n[5/5] Gán Floating IP...")
    fip = _assign_floating_ip(server["id"])

    # --- Tổng kết ---
    print("\n" + "=" * 60)
    print("  THIẾT LẬP HOÀN TẤT!")
    print("=" * 60)
    print(f"  Network   : {network['name']}")
    print(f"  Subnet    : {subnet['name']} ({cidr})")
    print(f"  Router    : {router['name']}")
    print(f"  Sec Group : {sg['name']}")
    print(f"  VM        : {vm_name}")
    if fip:
        print(f"  Floating  : {fip['floating_ip_address']}")
        print(f"\n  Truy cập web: http://{fip['floating_ip_address']}")
    print("=" * 60)

    return {
        "network": network,
        "subnet": subnet,
        "router": router,
        "security_group": sg,
        "server": server,
        "floating_ip": fip,
    }


# ----- 7. Load Balancer -----
def menu_setup_loadbalancer():
    print("\n" + "=" * 60)
    print("  THIẾT LẬP LOAD BALANCER")
    print("=" * 60)

    # Chọn subnet
    print("\nChọn subnet cho Load Balancer VIP:")
    subnets = client.list_subnets()
    subnet = choose_from_list(subnets, label="subnet")
    if not subnet:
        return

    group = config.GROUP_NAME
    lb_name = ask("Tên Load Balancer", f"{group}_lb")

    # --- Tạo LB ---
    print(f"\n[1/4] Tạo Load Balancer '{lb_name}'...")
    lb = client.create_loadbalancer(lb_name, subnet["id"])
    lb_id = lb["id"]
    print(f"  LB ID: {lb_id}")
    print("  Đang đợi LB ACTIVE...")
    client.wait_lb_active(lb_id)

    # --- Listener ---
    print("\n[2/4] Tạo Listener...")
    listener_name = ask("Tên Listener", f"{group}_listener_http")
    port = int(ask("Port", "80"))
    listener = client.create_listener(lb_id, listener_name, "HTTP", port)
    print(f"  Listener: {listener['name']} (port {port})")
    client.wait_lb_active(lb_id)

    # --- Pool ---
    print("\n[3/4] Tạo Pool...")
    pool_name = ask("Tên Pool", f"{group}_pool_http")
    algorithm = ask("Thuật toán (ROUND_ROBIN/LEAST_CONNECTIONS/SOURCE_IP)", "ROUND_ROBIN")
    pool = client.create_pool(listener["id"], pool_name, "HTTP", algorithm)
    pool_id = pool["id"]
    print(f"  Pool: {pool['name']} ({algorithm})")
    client.wait_lb_active(lb_id)

    # --- Health Monitor ---
    print("\n[4/4] Tạo Health Monitor...")
    hm = client.create_healthmonitor(pool_id)
    print(f"  Health Monitor ID: {hm['id']}")
    client.wait_lb_active(lb_id)

    # --- Thêm members (các VMs hiện có) ---
    add_members = ask("Thêm các máy ảo hiện có vào pool? (y/n)", "y")
    if add_members.lower() == "y":
        servers = client.list_servers()
        active_servers = [s for s in servers if s.get("status") == "ACTIVE"]
        if not active_servers:
            print("  Không có máy ảo ACTIVE nào.")
        else:
            for s in active_servers:
                addrs = []
                for net_name, ips in s.get("addresses", {}).items():
                    for ip in ips:
                        if ip.get("OS-EXT-IPS:type") != "floating":
                            addrs.append(ip["addr"])
                if addrs:
                    add_this = ask(f"  Thêm '{s['name']}' ({addrs[0]}) vào pool? (y/n)", "y")
                    if add_this.lower() == "y":
                        member = client.create_member(
                            pool_id, s["name"], addrs[0], 80, subnet["id"]
                        )
                        print(f"    [OK] Đã thêm member: {s['name']} ({addrs[0]})")
                        client.wait_lb_active(lb_id)

    # Gán Floating IP cho LB
    assign_fip = ask("\nGán Floating IP cho Load Balancer? (y/n)", "y")
    lb_fip = None
    if assign_fip.lower() == "y":
        ext_net = client.find_external_network()
        if ext_net:
            lb = client.get_loadbalancer(lb_id)
            vip_port_id = lb.get("vip_port_id")
            fip = client.create_floating_ip(ext_net["id"])
            client.associate_floating_ip(fip["id"], vip_port_id)
            lb_fip = fip["floating_ip_address"]
            print(f"[OK] LB Floating IP: {lb_fip}")

    print("\n" + "=" * 60)
    print("  LOAD BALANCER ĐÃ THIẾT LẬP!")
    print("=" * 60)
    print(f"  LB Name    : {lb_name}")
    print(f"  Listener   : port {port}")
    print(f"  Pool       : {pool_name} ({algorithm})")
    if lb_fip:
        print(f"  Floating IP: {lb_fip}")
        print(f"\n  Truy cập LB: http://{lb_fip}")
    print("=" * 60)

    return {"lb": lb, "listener": listener, "pool": pool, "pool_id": pool_id}


def menu_list_loadbalancers():
    print("\n=== DANH SÁCH LOAD BALANCERS ===")
    lbs = client.list_loadbalancers()
    rows = []
    for lb in lbs:
        rows.append([
            lb.get("id", ""),
            lb.get("name", ""),
            lb.get("provisioning_status", ""),
            lb.get("vip_address", ""),
        ])
    print_table(["ID", "Name", "Status", "VIP Address"], rows)
    print(f"\nTổng: {len(lbs)} load balancer(s)")


def menu_delete_loadbalancer():
    print("\n=== XÓA LOAD BALANCER ===")
    lbs = client.list_loadbalancers()
    lb = choose_from_list(lbs, label="LB cần xóa")
    if lb:
        confirm = ask(f"Xác nhận xóa LB '{lb['name']}'? (cascade) (y/n)", "n")
        if confirm.lower() == "y":
            client.delete_loadbalancer(lb["id"], cascade=True)
            print(f"[OK] Đã xóa LB: {lb['name']}")


# ----- 8. Tăng / Giảm máy ảo (Auto-scale) -----
def menu_scale_vms():
    print("\n" + "=" * 60)
    print("  TĂNG / GIẢM SỐ LƯỢNG MÁY ẢO")
    print("=" * 60)

    # Chọn pool
    print("\nChọn Pool của Load Balancer:")
    pools = client.list_pools()
    pool = choose_from_list(pools, label="pool")
    if not pool:
        return
    pool_id = pool["id"]

    # Hiện members hiện tại
    members = client.list_members(pool_id)
    print(f"\nSố member hiện tại: {len(members)}")
    for m in members:
        print(f"  - {m.get('name', 'N/A')} ({m.get('address', '')}) "
              f"[{m.get('operating_status', '')}]")

    print("\n  1. Tăng (thêm máy ảo mới)")
    print("  2. Giảm (xóa máy ảo)")
    print("  3. Quay lại")
    choice = ask("Chọn", "1")

    if choice == "1":
        _scale_up(pool_id, pool)
    elif choice == "2":
        _scale_down(pool_id, pool)


def _scale_up(pool_id, pool):
    """Tăng thêm máy ảo và thêm vào LB pool."""
    count = int(ask("Số máy ảo cần thêm", "1"))
    group = config.GROUP_NAME

    # Chọn cấu hình
    print("\nChọn Image:")
    images = client.list_images()
    image = choose_from_list(images, label="image")
    if not image:
        return

    flavor = pick_compatible_flavor(image)
    boot_opts = resolve_boot_options(flavor, image, interactive=False)

    print("\nChọn Network:")
    nets = client.list_networks()
    user_nets = [n for n in nets if not n.get("router:external")]
    net = choose_from_list(user_nets, label="network")
    if not net:
        return

    # Tìm subnet
    subnets = client.list_subnets()
    net_subnets = [s for s in subnets if s.get("network_id") == net["id"]]
    if not net_subnets:
        print("[LỖI] Network không có subnet!")
        return
    subnet = net_subnets[0]

    # Tìm LB ID từ pool
    lb_id = None
    lbs = client.list_loadbalancers()
    listeners = client.list_listeners()
    pool_listener = None
    for l in listeners:
        if pool_id in l.get("pools", []) or any(
            p.get("id") == pool_id for p in [{"id": pid} for pid in l.get("pools", [])]
        ):
            pool_listener = l
            break
    # Tìm LB từ listeners
    for l in listeners:
        for lb in lbs:
            if l.get("id") in lb.get("listeners", []) or any(
                li.get("id") == l.get("id") for li in [{"id": lid} for lid in lb.get("listeners", [])]
            ):
                lb_id = lb["id"]
                break

    user_data = generate_userdata_script()

    # Tìm index cao nhất
    servers = client.list_servers()
    existing = [s["name"] for s in servers]
    idx = len(existing) + 1

    for i in range(count):
        vm_name = f"{group}_vm{idx + i}"
        print(f"\n--- Tạo máy ảo {i+1}/{count}: {vm_name} ---")

        server = client.create_server(
            vm_name, image["id"], flavor["id"], net["id"],
            user_data=user_data,
            boot_from_volume=boot_opts["boot_from_volume"],
            volume_size=boot_opts["volume_size"],
        )
        print(f"  Server ID: {server['id']}")
        print("  Đang đợi ACTIVE...")
        srv = client.wait_server_active(server["id"])

        # Lấy IP private
        ip_addr = None
        for net_name, ips in srv.get("addresses", {}).items():
            for ip in ips:
                if ip.get("OS-EXT-IPS:type") != "floating":
                    ip_addr = ip["addr"]
                    break
            if ip_addr:
                break

        if ip_addr and lb_id:
            client.wait_lb_active(lb_id)
            member = client.create_member(pool_id, vm_name, ip_addr, 80, subnet["id"])
            print(f"  [OK] Đã thêm vào LB pool: {vm_name} ({ip_addr})")
        elif ip_addr:
            member = client.create_member(pool_id, vm_name, ip_addr, 80, subnet["id"])
            print(f"  [OK] Đã thêm vào pool: {vm_name} ({ip_addr})")

    print(f"\n[OK] Đã thêm {count} máy ảo vào hệ thống!")


def _scale_down(pool_id, pool):
    """Giảm máy ảo và xóa khỏi LB pool."""
    members = client.list_members(pool_id)
    if not members:
        print("  Không có member nào trong pool.")
        return

    print("\nChọn member cần xóa:")
    member = choose_from_list(members, label="member")
    if not member:
        return

    confirm = ask(f"Xác nhận xóa member '{member.get('name', member['id'])}'? (y/n)", "n")
    if confirm.lower() != "y":
        return

    # Xóa member khỏi pool
    client.delete_member(pool_id, member["id"])
    print(f"[OK] Đã xóa member khỏi pool: {member.get('name', member['id'])}")

    # Xóa luôn server?
    del_vm = ask("Xóa luôn máy ảo tương ứng? (y/n)", "y")
    if del_vm.lower() == "y":
        servers = client.list_servers()
        target = None
        for s in servers:
            for net_name, ips in s.get("addresses", {}).items():
                for ip in ips:
                    if ip["addr"] == member.get("address"):
                        target = s
                        break
        if target:
            # Xóa floating IP
            fips = client.list_floating_ips()
            ports = client.list_ports(device_id=target["id"])
            port_ids = {p["id"] for p in ports}
            for fip in fips:
                if fip.get("port_id") in port_ids:
                    client.delete_floating_ip(fip["id"])

            client.delete_server(target["id"])
            print(f"[OK] Đã xóa máy ảo: {target['name']}")
        else:
            print("  Không tìm thấy máy ảo tương ứng.")


# ----- Security Groups -----
def menu_list_security_groups():
    print("\n=== DANH SÁCH SECURITY GROUPS ===")
    sgs = client.list_security_groups()
    rows = []
    for sg in sgs:
        rows.append([
            sg.get("id", ""),
            sg.get("name", ""),
            sg.get("description", ""),
            len(sg.get("security_group_rules", [])),
        ])
    print_table(["ID", "Name", "Description", "Rules"], rows)
    print(f"\nTổng: {len(sgs)} security group(s)")


# ----- Floating IPs -----
def menu_list_floating_ips():
    print("\n=== DANH SÁCH FLOATING IPs ===")
    fips = client.list_floating_ips()
    rows = []
    for f in fips:
        rows.append([
            f.get("id", ""),
            f.get("floating_ip_address", ""),
            f.get("fixed_ip_address", "") or "N/A",
            f.get("status", ""),
            (f.get("port_id") or "N/A")[:12],
        ])
    print_table(["ID", "Floating IP", "Fixed IP", "Status", "Port ID"], rows)
    print(f"\nTổng: {len(fips)} floating IP(s)")


# ============================================================
#  MAIN MENU
# ============================================================
def main_menu():
    while True:
        print("\n" + "=" * 60)
        print("  OPENSTACK RESOURCE MANAGER - NT533 Lab 2")
        print("  UIT Cloud - " + config.GROUP_NAME)
        print("=" * 60)
        print("""
  ===== QUẢN LÝ TÀI NGUYÊN =====
   1.  Liệt kê Flavors
   2.  Liệt kê Images
   3.  Liệt kê Networks
   4.  Tạo Network (+ Subnet)
   5.  Xóa Network
   6.  Liệt kê Subnets
   7.  Tạo Subnet
   8.  Xóa Subnet
   9.  Liệt kê Routers
  10.  Tạo Router
  11.  Xóa Router
  12.  Liệt kê máy ảo (Instances)
  13.  Tạo máy ảo
  14.  Xóa máy ảo

  ===== SECURITY & NETWORKING =====
  15.  Liệt kê Security Groups
  16.  Liệt kê Floating IPs

  ===== THIẾT LẬP HOÀN CHỈNH =====
  20.  [AUTO] Thiết lập mạng + Tạo VM

  ===== LOAD BALANCER =====
  30.  Thiết lập Load Balancer
  31.  Liệt kê Load Balancers
  32.  Xóa Load Balancer

  ===== SCALE UP / DOWN =====
  40.  Tăng / Giảm máy ảo

  ===== HỆ THỐNG =====
   0.  Thoát
""")
        choice = input("Chọn chức năng: ").strip()

        try:
            if choice == "0":
                print("Tạm biệt!")
                sys.exit(0)
            elif choice == "1":
                menu_list_flavors()
            elif choice == "2":
                menu_list_images()
            elif choice == "3":
                menu_list_networks()
            elif choice == "4":
                menu_create_network()
            elif choice == "5":
                menu_delete_network()
            elif choice == "6":
                menu_list_subnets()
            elif choice == "7":
                menu_create_subnet()
            elif choice == "8":
                menu_delete_subnet()
            elif choice == "9":
                menu_list_routers()
            elif choice == "10":
                menu_create_router()
            elif choice == "11":
                menu_delete_router()
            elif choice == "12":
                menu_list_servers()
            elif choice == "13":
                menu_create_server()
            elif choice == "14":
                menu_delete_server()
            elif choice == "15":
                menu_list_security_groups()
            elif choice == "16":
                menu_list_floating_ips()
            elif choice == "20":
                menu_full_setup()
            elif choice == "30":
                menu_setup_loadbalancer()
            elif choice == "31":
                menu_list_loadbalancers()
            elif choice == "32":
                menu_delete_loadbalancer()
            elif choice == "40":
                menu_scale_vms()
            else:
                print("Lựa chọn không hợp lệ!")
        except Exception as e:
            print(f"\n[LỖI] {e}")

        pause()


# ============================================================
#  ENTRY POINT
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  OPENSTACK RESOURCE MANAGER")
    print("  NT533 - Hệ tính toán phân bố - Lab 2")
    print("  UIT Cloud Platform")
    print("=" * 60)

    print("\nĐang xác thực với OpenStack...")
    try:
        client.authenticate()
    except Exception as e:
        print(f"[LỖI] Xác thực thất bại: {e}")
        sys.exit(1)

    main_menu()
