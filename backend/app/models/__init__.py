from .entities import *
from .extended import *
from .auth import *
from .knowledge_chunks import *
from .v7 import *
from .v8 import *

from .v9 import *

from .v10 import *

from .v11 import *

from .v12 import *

from .v13 import *

from .v14 import *

from .v15 import *

from .v16 import *
from .v36 import *
from .v37 import *
from .work_graph import *
from .tool_access import *

from .routines import *  # noqa: E402,F401,F403  (D3.4)
from .team import *  # noqa: E402,F401,F403  (M2)
from .agent_hr import *  # noqa: E402,F401,F403  (M3)

# D3.5: hook ORM của Hộp việc (approval mới → inbox + hạn duyệt; có kết quả →
# đóng dòng inbox). Đăng ký ở đây để mọi đường tạo approval — API, worker, test
# chỉ dùng ORM — đều đi qua cùng một chỗ.
from app.services import inbox as _inbox_hooks  # noqa: E402,F401
from .learning import *  # noqa: E402,F401,F403  (M5b việc 9)
from .a2a import *  # noqa: E402,F401,F403  (M6 việc 12b)
from .company_foundation import *  # noqa: E402,F401,F403  (M2b nền công ty)
from .company_ops import *  # noqa: E402,F401,F403  (M2c vận hành công ty)
from .agent_native import *  # noqa: E402,F401,F403  (M2e công ty agent-native)
from .company_access import *  # noqa: E402,F401,F403  (R1 vai trò theo công ty)
from .leases import *  # noqa: E402,F401,F403  (R2 cho thuê agent)
from .documents import *  # noqa: E402,F401,F403  (M3a thư viện tài liệu)
from .catalog import *  # noqa: E402,F401,F403  (M3f sản phẩm & bảng giá)
from .doc_ingest import *  # noqa: E402,F401,F403  (M3c nạp tài liệu)
from .crm import *  # noqa: E402,F401,F403  (M3g khách hàng & đồng ý DLCN)
from .contracts import *  # noqa: E402,F401,F403  (M3h hợp đồng & đối tác)
from .meetings import *  # noqa: E402,F401,F403  (M3i họp & quyết định)
from .finance import *  # noqa: E402,F401,F403  (M3j tài chính kinh doanh)
