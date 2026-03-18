# OpenStack Resource Manager - NT533 Lab 1

Ứng dụng Python quản lý tài nguyên OpenStack qua REST API cho môn **NT533 - Hệ tính toán phân bố**.

## Cấu trúc dự án

```
OpenStack/
├── config.py              # Cấu hình endpoints & thông tin xác thực
├── openstack_client.py    # Module gọi OpenStack REST API
├── app.py                 # Ứng dụng chính (menu-driven)
└── README.md              # Hướng dẫn sử dụng
```

## Yêu cầu

- Python 3.7+
- Thư viện `requests`

```bash
pip install requests
```

## Cấu hình

Chỉnh sửa file `config.py`:

```python
AUTH_USERNAME = "your_username"
AUTH_PASSWORD = "your_password"
AUTH_PROJECT_NAME = "your_project"
GROUP_NAME = "Nhom01"
GROUP_MEMBERS = "Nguyen Van A, Tran Van B"
EXTERNAL_NETWORK_NAME = "external-network"
```

## Chạy ứng dụng

```bash
python app.py
```

## Chức năng

| # | Chức năng | Mô tả |
|---|-----------|--------|
| 1 | Liệt kê Flavors | Hiển thị tất cả flavor (vCPU, RAM, Disk) |
| 2 | Liệt kê Images | Hiển thị tất cả image khả dụng |
| 3-5 | Quản lý Network | Liệt kê, tạo, xóa Network |
| 6-8 | Quản lý Subnet | Liệt kê, tạo, xóa Subnet |
| 9-11 | Quản lý Router | Liệt kê, tạo (+ external gateway), xóa Router |
| 12-14 | Quản lý VM | Liệt kê, tạo (+ user data), xóa máy ảo |
| 15 | Security Groups | Liệt kê Security Groups |
| 16 | Floating IPs | Liệt kê Floating IPs |
| **20** | **Auto Setup** | **Tự động tạo Network + Subnet + Router + SG + VM + Floating IP** |
| 30-32 | Load Balancer | Thiết lập, liệt kê, xóa Load Balancer (Octavia) |
| **40** | **Scale Up/Down** | **Tăng/giảm VM tự động thêm/xóa khỏi LB pool** |

## Luồng thiết lập hoàn chỉnh (Option 20)

1. Tạo **Network** + **Subnet** (CIDR tùy chọn)
2. Tạo **Router** kết nối External Network ↔ Internal Subnet
3. Tạo **Security Group** (SSH/HTTP/HTTPS/ICMP)
4. Tạo **máy ảo** với **cloud-init user data** (tự động cài Nginx + trang web nhóm)
5. Gán **Floating IP** cho VM

## Load Balancer (Option 30)

1. Tạo Load Balancer trên subnet
2. Tạo Listener (HTTP port 80)
3. Tạo Pool (ROUND_ROBIN)
4. Tạo Health Monitor
5. Thêm VM members vào pool
6. Gán Floating IP cho LB VIP

## Scale Up/Down (Option 40)

- **Scale Up**: Tạo VM mới → tự động cài web server → thêm vào LB pool
- **Scale Down**: Chọn member xóa khỏi pool → tùy chọn xóa luôn VM

## API Endpoints sử dụng

| Service | Endpoint |
|---------|----------|
| Identity (Keystone) | `https://cloud-identity.uitiot.vn/v3/` |
| Compute (Nova) | `https://cloud-compute.uitiot.vn/v2.1` |
| Image (Glance) | `https://cloud-image.uitiot.vn` |
| Network (Neutron) | `https://cloud-network.uitiot.vn` |
| Load Balancer (Octavia) | `https://cloud-loadbalancer.uitiot.vn` |
