NOTICES = {
    'maintenance': (
        '【通知】关于{place}网络维护的通知',
        """尊敬的客户，您好：

为保障网络稳定运行，将对{place}相关线路进行维护操作，详情如下：

维护时间：
北京时间（UTC+8）：{start} - {end}
UTC 时间：{utc_start} - {utc_end}

影响范围：
{impact}

维护影响：
维护期间，{place}相关网络可能会出现短时中断、访问波动、时延升高或丢包。
预计业务中断时长约为{duration}。
事由：{reason}

由此给您带来的不便，我们深表歉意，感谢您的理解与支持。

ZENLENET PTE. LTD.
""",
    ),
    'cutover': (
        '【通知】关于{place}线路割接的通知',
        """尊敬的客户：

您好！

为了进一步提升网络与业务的长期稳定性，我司计划对{place}进行线路割接。

割接事由：
{reason}

影响范围：
{impact}

割接时间：
北京时间：{start} - {end}
UTC时间：{utc_start} - {utc_end}

割接期间，影响范围内的业务会出现中断。建议在窗口开始前将流量切换至备用链路。
预计影响时长约为{duration}。

ZENLENET PTE. LTD.
""",
    ),
    'risk': (
        '【提醒】关于{place}上游运营商维护的风险提示',
        """尊敬的客户，您好：

上游运营商计划对{place}相关线路进行维护。

维护时间：
北京时间 {start} - {end}
UTC时间 {utc_start} - {utc_end}

涉及范围：
{impact}

本次为风险提示，预计不会造成直接中断。维护窗口内服务处于 At Risk 状态，可能出现波动、时延升高或丢包。
事由：{reason}

ZENLENET PTE. LTD.
""",
    ),
    'emergency': (
        '【紧急通知】关于{place}紧急维护的通知',
        """紧急通知
尊敬的客户，您好：

因{reason}，将对{place}进行紧急维护。

维护时间：
北京时间：{start} - {end}
UTC时间：{utc_start} - {utc_end}

影响范围：
{impact}

维护期间可能会出现约{duration}的网络波动或业务中断。

ZENLENET PTE. LTD.
""",
    ),
    'sdwan': (
        '【通知】关于接入点服务器维护的通知',
        """尊敬的客户，您好：

接入点 / SD-WAN 将进行维护调整。

节点：{place}
维护时间：
北京时间（UTC+8）：{start} - {end}
UTC时间：{utc_start} - {utc_end}

影响范围：
{impact}

预计影响时长约为{duration}。
事由：{reason}

ZENLENET PTE. LTD.
""",
    ),
}
