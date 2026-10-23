# 注意力优化插件

为 AstrBot 提供按群成员隔离的限时续聊功能。机器人被明确唤醒后，同一成员可在窗口内继续交谈，无需重复使用唤醒词或 @机器人。

## 功能

- 支持唤醒词、@机器人及引用机器人消息触发续聊窗口。
- 窗口按平台实例、机器人账号、群和成员分别管理。
- 支持回复后续时、固定时长、生效群范围和纯媒体消息续聊。
- 可跳过明确发给其他成员的消息，保留 AstrBot 的指令、权限和访问控制。
- 无额外模型调用或运行依赖。

## 环境要求

- AstrBot `>=4.29.1,<5`。
- Python `>=3.10`。
- 通过 `aiocqhttp` 适配器接入 OneBot v11，例如 NapCat 或 SnowLuma。
- 已配置并启用聊天模型。

## 安装

1. 打开 AstrBot 管理面板的插件页面，选择通过仓库链接安装。
2. 输入仓库地址：

   ```text
   https://github.com/lociere/astrbot_plugin_attention
   ```

3. 安装完成后启用插件，在插件配置中设置续聊时长和生效范围。

也可通过面板的本地安装入口上传插件 ZIP。配置由 AstrBot 保存在 `data/config/astrbot_plugin_attention_config.json`。

## 使用

在群里通过当前 AstrBot 的唤醒词、@机器人或引用机器人消息开始对话。窗口内，同一成员发送的后续消息可继续触发回复；其他成员仍需分别唤醒。

默认窗口为 **90 秒**，机器人回答后重新计时。关闭 `refresh_on_reply` 后，窗口从最近一次明确唤醒开始固定计时。窗口超时后恢复 AstrBot 原有唤醒规则。

如需仅在明确唤醒及续聊窗口内回复，请在 AstrBot 中关闭“群聊上下文感知 → 主动回复”。插件不撤销其他功能已触发的唤醒。

## 配置

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | 启用插件 |
| `window_seconds` | float | `90` | 续聊窗口长度，范围 1—3600 秒 |
| `refresh_on_reply` | bool | `true` | 回答后重新计时；关闭后使用固定窗口 |
| `allowed_groups` | list | `[]` | 生效群号或完整会话标识；留空不额外限制 |
| `ignore_addressed_to_others` | bool | `true` | 不为 @其他人、@全体或引用他人消息补充唤醒；同时明确呼叫机器人时仍可处理 |
| `allow_media` | bool | `true` | 允许窗口内的纯表情、图片、语音等消息续聊 |
| `max_sessions` | int | `1000` | 最多保留的窗口数，范围 1—10000；超限淘汰最早到期项 |

## 行为与限制

- 仅作用于群聊。私聊、已匹配指令、白名单、权限和模型开关继续按 AstrBot 配置处理。
- 插件调整续聊消息的唤醒资格，后续回复生成、上下文、工具调用、分段和发送均使用现有处理流程。
- 窗口不通过语义判断消息在对谁说。同一成员转向他人聊天但未使用 @或引用时，仍可能触发机器人。
- `allow_media` 只决定是否允许纯媒体消息续聊，媒体理解能力取决于模型与其他插件。
- 窗口只保存在内存中，重载或重启后清空。仅收到消息不会延长窗口；回复续时依据框架事件，不代表平台送达回执。

## 开发

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p 'test_*.py' -v
ruff check .
ruff format --check .
python tools/package.py
```

安装 AstrBot 4.29.1 后，可运行 SDK 集成检查：

```bash
python tests/sdk_smoke.py
```

## 许可

[MIT License](LICENSE)
