创建我的APIKey
点击跳转至官网创建V5APIKey的页面 创建我的APIKey

生成APIKey
在对任何请求进行签名之前，您必须通过交易网站创建一个APIKey。创建APIKey后，您将获得3个必须记住的信息：

APIKey
SecretKey
Passphrase
APIKey和SecretKey将由平台随机生成和提供，Passphrase将由您提供以确保API访问的安全性。平台将存储Passphrase加密后的哈希值进行验证，但如果您忘记Passphrase，则无法恢复，请您通过交易网站重新生成新的APIKey。

本项目模拟盘API信息（记录）
备注名：AlgorithmTrader_Simulated
权限：读取/交易
IP 绑定：未绑定
.env 对应字段：
OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE / OKX_SIMULATED_TRADING


APIKey 权限
APIKey 有如下3种权限，一个 APIKey 可以有一个或多个权限。

读取 ：查询账单和历史记录等 读权限
提现 ：可以进行提币
交易 ：可以下单和撤单，转账，调整配置 等写权限
APIKey 安全性
 为了提高安全性，我们建议您将 APIKey 绑定 IP
每个APIKey最多可绑定20个IP地址，IP地址支持IPv4/IPv6和网段的格式。
 未绑定IP且拥有交易或提币权限的APIKey，将在闲置14天之后自动删除。(模拟盘的 API key 不会被删除)
用户调用了需要 APIKey 鉴权的接口，才会被视为 APIKey 被使用。
调用了不需要 APIKey 鉴权的接口，即使传入了 APIKey的信息，也不会被视为使用过。
Websocket 只有在登陆的时候，才会被视为 APIKey 被使用过。在登陆后的连接中做任何操作（如 订阅/下单），也不会被认为 APIKey 被使用，这点需要注意。
用户可以在 安全中心 中看到未绑定IP且拥有交易/提现权限的 APIKey 最近使用记录。

REST 请求验证
发起请求
所有REST私有请求头都必须包含以下内容：

OK-ACCESS-KEY字符串类型的APIKey。

OK-ACCESS-SIGN使用HMAC SHA256哈希函数获得哈希值，再使用Base-64编码（请参阅签名）。

OK-ACCESS-TIMESTAMP发起请求的时间（UTC），如：2020-12-08T09:08:57.715Z

OK-ACCESS-PASSPHRASE您在创建API密钥时指定的Passphrase。

所有请求都应该含有application/json类型内容，并且是有效的JSON。

签名
生成签名

OK-ACCESS-SIGN的请求头是对timestamp + method + requestPath + body字符串（+表示字符串连接），以及SecretKey，使用HMAC SHA256方法加密，通过Base-64编码输出而得到的。

如：sign=CryptoJS.enc.Base64.stringify(CryptoJS.HmacSHA256(timestamp + 'GET' + '/api/v5/account/balance?ccy=BTC', SecretKey))

其中，timestamp的值与OK-ACCESS-TIMESTAMP请求头相同，为ISO格式，如2020-12-08T09:08:57.715Z。

method是请求方法，字母全部大写：GET/POST。

requestPath是请求接口路径。如：/api/v5/account/balance

body是指请求主体的字符串，如果请求没有主体（通常为GET请求）则body可省略。如：{"instId":"BTC-USDT","lever":"5","mgnMode":"isolated"}

 GET请求参数是算作requestPath，不算body
SecretKey为用户申请APIKey时所生成。如：22582BD0CFF14C41EDBF1AB98506286D

WebSocket
概述
WebSocket是HTML5一种新的协议（Protocol）。它实现了用户端与服务器全双工通信， 使得数据可以快速地双向传播。通过一次简单的握手就可以建立用户端和服务器连接， 服务器根据业务规则可以主动推送信息给用户端。其优点如下：

用户端和服务器进行数据传输时，请求头信息比较小，大概2个字节。
用户端和服务器皆可以主动地发送数据给对方。
不需要多次创建TCP请求和销毁，节约宽带和服务器的资源。
 强烈建议开发者使用WebSocket API获取市场行情和买卖深度等信息。
连接
连接限制：3 次/秒 (基于IP)

当订阅公有频道时，使用公有服务的地址；当订阅私有频道时，使用私有服务的地址

请求限制：

每个连接 对于 订阅/取消订阅/登录 请求的总次数限制为 480 次/小时

如果出现网络问题，系统会自动断开连接

如果连接成功后30s未订阅或订阅后30s内服务器未向用户推送数据，系统会自动断开连接

为了保持连接有效且稳定，建议您进行以下操作：

1. 每次接收到消息后，用户设置一个定时器，定时N秒，N 小于30。

2. 如果定时器被触发（N 秒内没有收到新消息），发送字符串 'ping'。

3. 期待一个文字字符串'pong'作为回应。如果在 N秒内未收到，请发出错误或重新连接。

连接限制
子账户维度，订阅每个 WebSocket 频道的最大连接数为 30 个。每个 WebSocket 连接都由唯一的 connId 标识。



受此限制的 WebSocket 频道如下：

订单频道
账户频道
持仓频道
账户余额和持仓频道
爆仓风险预警推送频道
账户greeks频道
若用户通过不同的请求参数在同一个 WebSocket 连接下订阅同一个频道，如使用 {"channel": "orders", "instType": "ANY"} 和 {"channel": "orders", "instType": "SWAP"}，只算为一次连接。若用户使用相同或不同的 WebSocket 连接订阅上述频道，如订单频道和账户频道。在该两个频道之间，计数不会累计，因为它们被视作不同的频道。简言之，系统计算每个频道对应的 WebSocket 连接数量。



新链接订阅频道时，平台将对该订阅返回channel-conn-count的消息同步链接数量。

链接数量更新

{
    "event":"channel-conn-count",
    "channel":"orders",
    "connCount": "2",
    "connId":"abcd1234"
}



当超出限制时，一般最新订阅的链接会收到拒绝。用户会先收到平时的订阅成功信息然后收到channel-conn-count-error消息，代表平台终止了这个链接的订阅。在异常场景下平台会终止已订阅的现有链接。

链接数量限制报错

{
    "event": "channel-conn-count-error",
    "channel": "orders",
    "connCount": "30",
    "connId":"a4d3ae55"
}



通过 WebSocket 进行的订单操作，例如下单、修改和取消订单，不会受到此改动影响。

登录
请求示例

{
 "op": "login",
 "args":
  [
     {
       "apiKey": "******",
       "passphrase": "******",
       "timestamp": "1538054050",
       "sign": "7L+zFQ+CEgGu5rzCj4+BdV2/uUHGqddA9pI6ztsRRPs=" 
      }
   ]
}
请求参数
参数	类型	是否必须	描述
op	String	是	操作，login
args	Array of objectss	是	账户列表
> apiKey	String	是	APIKey
> passphrase	String	是	APIKey 的密码
> timestamp	String	是	时间戳，Unix Epoch时间，单位是秒
> sign	String	是	签名字符串
全部成功返回示例

{
  "event": "login",
  "code": "0",
  "msg": "",
  "connId": "a4d3ae55"
}
全部失败返回示例

{
  "event": "error",
  "code": "60009",
  "msg": "Login failed.",
  "connId": "a4d3ae55"
}
返回参数
参数	类型	是否必须	描述
event	String	是	操作，login error
code	String	否	错误码
msg	String	否	错误消息
connId	String	是	WebSocket连接ID
apiKey:调用API的唯一标识。需要用户手动设置一个 passphrase:APIKey的密码 timestamp:Unix Epoch 时间戳，单位为秒，如 1704876947 sign:签名字符串，签名算法如下：

先将timestamp 、 method 、requestPath 进行字符串拼接，再使用HMAC SHA256方法将拼接后的字符串和SecretKey加密，然后进行Base64编码

SecretKey:用户申请APIKey时所生成的安全密钥，如：22582BD0CFF14C41EDBF1AB98506286D

其中 timestamp 示例:const timestamp = '' + Date.now() / 1,000

其中 sign 示例: sign=CryptoJS.enc.Base64.stringify(CryptoJS.HmacSHA256(timestamp +'GET'+ '/users/self/verify', secret))

method 总是 'GET'

requestPath 总是 '/users/self/verify'

 请求在时间戳之后30秒会失效，如果您的服务器时间和API服务器时间有偏差，推荐使用 REST API查询API服务器的时间，然后设置时间戳
订阅
订阅说明

请求格式说明

{
    "op": "subscribe",
    "args": ["<SubscriptionTopic>"]
}
WebSocket 频道分成两类： 公共频道 和 私有频道

公共频道无需登录，包括行情频道，K线频道，交易数据频道，资金费率频道，限价范围频道，深度数据频道，标记价格频道等。

私有频道需登录，包括用户账户频道，用户交易频道，用户持仓频道等。

用户可以选择订阅一个或者多个频道，多个频道总长度不能超过 64 KB。

以下是一个请求参数的例子。每一个频道的请求参数的要求都不一样。请根据每一个频道的需求来订阅频道。

请求示例

{
    "op":"subscribe",
    "args":[
        {
            "channel":"tickers",
            "instId":"BTC-USDT"
        }
    ]
}

请求参数

参数	类型	是否必须	描述
op	String	是	操作，subscribe
args	Array of objects	是	请求订阅的频道列表
> channel	String	是	频道名
> instType	String	否	产品类型
SPOT：币币
MARGIN：币币杠杆
SWAP：永续
FUTURES：交割
OPTION：期权
ANY：全部
> instFamily	String	否	交易品种
适用于交割/永续/期权
> instId	String	否	产品ID
返回示例

{
    "event": "subscribe",
    "arg": {
        "channel": "tickers",
        "instId": "BTC-USDT"
    },
    "connId": "accb8e21"
}
返回参数

参数	类型	是否必须	描述
event	String	是	事件，subscribe error
arg	Object	否	订阅的频道
> channel	String	是	频道名
> instType	String	否	产品类型
SPOT：币币
MARGIN：币币杠杆
SWAP：永续
FUTURES：交割
OPTION：期权
ANY：全部
> instFamily	String	否	交易品种
适用于交割/永续/期权
> instId	String	否	产品ID
code	String	否	错误码
msg	String	否	错误消息
connId	String	是	WebSocket连接ID
取消订阅
可以取消一个或者多个频道

请求格式说明

{
    "op": "unsubscribe",
    "args": ["< SubscriptionTopic > "]
}
请求示例

{
  "op": "unsubscribe",
  "args": [
    {
      "channel": "tickers",
      "instId": "BTC-USDT"
    }
  ]
}
请求参数

参数	类型	是否必须	描述
op	String	是	操作，unsubscribe
args	Array of objects	是	取消订阅的频道列表
> channel	String	是	频道名
> instType	String	否	产品类型
SPOT：币币
MARGIN：币币杠杆
SWAP：永续合约
FUTURES：交割合约
OPTION：期权
ANY：全部
> instFamily	String	否	交易品种
适用于交割/永续/期权
> instId	String	否	产品ID
返回示例

{
    "event": "unsubscribe",
    "arg": {
        "channel": "tickers",
        "instId": "BTC-USDT"
    },
    "connId": "d0b44253"
}
返回参数

参数	类型	是否必须	描述
event	String	是	事件，unsubscribe error
arg	Object	否	取消订阅的频道
> channel	String	是	频道名
> instType	String	否	产品类型
SPOT：币币
MARGIN：币币杠杆
SWAP：永续合约
FUTURES：交割合约
OPTION：期权
ANY：全部
> instFamily	String	否	交易品种
适用于交割/永续/期权
> instId	String	否	产品ID
code	String	否	错误码
msg	String	否	错误消息
connId	String	是	WebSocket连接ID
通知
WebSocket有一种消息类型(event=notice)。


用户会在如下场景收到此类信息：

Websocket服务升级断线
在推送服务升级前60秒会推送信息，告知用户WebSocket服务即将升级。用户可以重新建立新的连接避免由于断线造成的影响。

返回示例

{
    "event": "notice",
    "code": "64008",
    "msg": "The connection will soon be closed for a service upgrade. Please reconnect.",
    "connId": "a4d3ae55"
}


目前支持WebSocket公共频道(/ws/v5/public)和私有频道(/ws/v5/private)。

账户模式
为了方便您的交易体验，请在开始交易前设置适当的账户模式。

交易账户交易系统提供四个账户模式，分别为现货模式、合约模式、跨币种保证金模式以及组合保证金模式。

账户模式的首次设置，需要在网页或手机app上进行。

实盘交易
实盘API交易地址如下：

REST：https://www.okx.com
WebSocket公共频道：wss://ws.okx.com:8443/ws/v5/public
WebSocket私有频道：wss://ws.okx.com:8443/ws/v5/private
WebSocket业务频道：wss://ws.okx.com:8443/ws/v5/business
模拟盘交易
目前可以进行 API 的模拟盘交易，部分功能不支持如提币、充值、申购赎回等。

模拟盘API交易地址如下：

REST：https://www.okx.com
WebSocket公共频道：wss://wspap.okx.com:8443/ws/v5/public
WebSocket私有频道：wss://wspap.okx.com:8443/ws/v5/private
WebSocket业务频道：wss://wspap.okx.com:8443/ws/v5/business
模拟盘的账户与欧易的账户是互通的，如果您已经有欧易账户，可以直接登录。

模拟盘API交易需要在模拟盘上创建APIKey：

登录欧易账户—>交易—>模拟交易—>个人中心—>创建模拟盘APIKey—>开始模拟交易
