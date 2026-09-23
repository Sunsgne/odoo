# 部署说明

模块目录：`/opt/zenlenet/odoo/addons/zenlenet_ops`，Odoo 以官方镜像 `odoo:19` 运行在 `/opt/zenlenet/odoo` 的 docker compose 里。

## 每次更新模块

```bash
tar czf /tmp/zenlenet_ops.tgz -C custom_addons zenlenet_ops
scp /tmp/zenlenet_ops.tgz root@<server>:/tmp/
ssh root@<server> '
  rm -rf /opt/zenlenet/odoo/addons/zenlenet_ops &&
  tar xzf /tmp/zenlenet_ops.tgz -C /opt/zenlenet/odoo/addons &&
  cd /opt/zenlenet/odoo &&
  docker compose stop odoo &&
  docker compose run --rm --name odoo-upgrade odoo odoo -d zenlenet -u zenlenet_ops --stop-after-init &&
  docker compose start odoo'
```

**任何改动（包括只改 `static/` 下的 SCSS / JS / XML）都必须走 `-u zenlenet_ops` 升级。**

原因：Odoo 19 的样式包 URL 形如 `/web/assets/<hash>/web.assets_web.min.css`，`<hash>` 取自各源文件
`ir.attachment` 的 `write_date`，而不是磁盘文件的修改时间；浏览器又按 `Cache-Control: immutable` 缓存一年。
只 scp 文件、不升级模块，URL 不变，浏览器会一直用旧样式包；如果旧包里有编译错误，用户就会持续看到
「样式错误，样式编译失败」。`-u` 会刷新源文件附件，URL 随之变化，所有浏览器自动拿到新包。

## 样式编译器

Odoo 19 用内置 libsass 编译 SCSS，不支持 `min()` / `max()` 里混合单位（例如 `min(280px, 90vw)`），会导致整站
样式回退。改 SCSS 后先看升级日志有没有 `Internal Error`，再在浏览器确认。

## nginx

`nginx-locations.conf` 是加到站点配置里的 location 片段（含 `/report` 给 wkhtmltopdf 使用）。
