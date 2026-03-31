# ============================================================
# OpenStack API Configuration - UIT Cloud
# ============================================================
# Điền thông tin xác thực OpenStack của bạn vào đây
# Lấy từ Horizon Dashboard > Identity > Application Credentials
# hoặc từ file openrc
# ============================================================

# --- Endpoints ---
IDENTITY_URL = "https://cloud-identity.uitiot.vn/v3"
COMPUTE_URL = "https://cloud-compute.uitiot.vn/v2.1"
IMAGE_URL = "https://cloud-image.uitiot.vn"
NETWORK_URL = "https://cloud-network.uitiot.vn"
LOADBALANCER_URL = "https://cloud-loadbalancer.uitiot.vn"
PLACEMENT_URL = "https://cloud-placement.uitiot.vn"
VOLUME_URL = "https://cloud-volume.uitiot.vn/v3"

# --- Authentication ---
# Chọn phương thức xác thực: "password" hoặc "application_credential"
AUTH_METHOD = "password"

# Phương thức 1: Username/Password
# AUTH_USERNAME = ""       # VD: "student01"
# AUTH_PASSWORD = ""       # VD: "mypassword"
# AUTH_PROJECT_NAME = ""   # VD: "nhom01"
# AUTH_PROJECT_ID = ""           # Có thể để trống. Nếu có, sẽ ưu tiên hơn AUTH_PROJECT_NAME
# AUTH_USER_DOMAIN_NAME = "Default"
# AUTH_PROJECT_DOMAIN_NAME = "Default"

# Phương thức 2: Application Credential
# Lấy tại Horizon > Identity > Application Credentials
APP_CRED_ID = ""               # Ưu tiên nếu có
APP_CRED_NAME = ""             # Dùng khi không có APP_CRED_ID
APP_CRED_SECRET = ""           # Secret của Application Credential

# --- Group Info (dùng cho web hiển thị) ---
GROUP_NAME = "Nhom06"            # VD: "Nhom01"
GROUP_MEMBERS = "Tan, Duy"  # Danh sách thành viên

# --- External Network ---
EXTERNAL_NETWORK_NAME = "external-network"  # Tên external network (provider)
