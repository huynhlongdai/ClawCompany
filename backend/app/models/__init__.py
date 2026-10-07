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

# D3.5: hook ORM của Hộp việc (approval mới → inbox + hạn duyệt; có kết quả →
# đóng dòng inbox). Đăng ký ở đây để mọi đường tạo approval — API, worker, test
# chỉ dùng ORM — đều đi qua cùng một chỗ.
from app.services import inbox as _inbox_hooks  # noqa: E402,F401
