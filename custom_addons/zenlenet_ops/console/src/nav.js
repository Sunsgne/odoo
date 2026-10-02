export const NAV = [
  { key: "home", label: "工作台" },
  {
    label: "客户",
    items: [
      { key: "customers", label: "客户", model: "res.partner", domain: [["is_company", "=", true], ["customer_rank", ">", 0]] },
      { key: "quotes", label: "报价", model: "sale.order", domain: [["state", "in", ["draft", "sent"]]] },
      { key: "contracts", label: "合同", model: "zenlenet.contract" },
    ],
  },
  {
    label: "财务",
    items: [
      { key: "invoices", label: "出账", model: "account.move", domain: [["move_type", "=", "out_invoice"]] },
      { key: "payments", label: "收款", model: "account.payment", domain: [["payment_type", "=", "inbound"]] },
      { key: "usage", label: "95 值用量", model: "zenlenet.usage" },
      { key: "charges", label: "收费项", model: "zenlenet.charge" },
      { key: "credits", label: "故障减免", model: "zenlenet.credit" },
      { key: "bills", label: "供应商账单", model: "account.move", domain: [["move_type", "=", "in_invoice"]] },
    ],
  },
  {
    label: "工单",
    items: [
      { key: "flows", label: "资源工单", model: "zenlenet.flow" },
      { key: "tasks", label: "交付任务", model: "zenlenet.flow.task" },
      { key: "tickets", label: "服务工单", model: "zenlenet.ticket" },
      { key: "labor", label: "人力", model: "zenlenet.labor" },
      { key: "maintenance", label: "维护通告", model: "zenlenet.maintenance" },
    ],
  },
  {
    label: "网络资源",
    items: [
      { key: "campus", label: "园区" },
      { key: "ipam", label: "地址管理" },
      { key: "prefixes", label: "地址段", model: "zenlenet.prefix" },
      { key: "addresses", label: "地址", model: "zenlenet.address" },
      { key: "lines", label: "线路", model: "zenlenet.line" },
      { key: "domains", label: "管理域", model: "zenlenet.ipam.domain" },
    ],
  },
  {
    label: "采购与资产",
    items: [
      { key: "suppliers", label: "供应商", model: "res.partner", domain: [["supplier_rank", ">", 0]] },
      { key: "purchase", label: "采购" },
      { key: "itam", label: "资产总览" },
      { key: "assets", label: "资产", model: "zenlenet.asset" },
      { key: "asset-tasks", label: "资产任务", model: "zenlenet.asset.task" },
    ],
  },
  {
    label: "排班",
    items: [
      { key: "duty", label: "排班日历" },
      { key: "duty-sheets", label: "排班表", model: "zenlenet.duty.sheet" },
      { key: "duty-shifts", label: "班次", model: "zenlenet.duty.shift" },
      { key: "duty-groups", label: "分组", model: "zenlenet.duty.group" },
      { key: "duty-swaps", label: "换班", model: "zenlenet.duty.swap" },
      { key: "duty-regions", label: "区域", model: "zenlenet.duty.region" },
    ],
  },
  {
    label: "设置",
    items: [
      { key: "users", label: "用户与角色", model: "res.users", domain: [["share", "=", false]] },
      { key: "products", label: "产品与定价", model: "product.template" },
    ],
  },
];

export function findPage(key) {
  for (const group of NAV) {
    if (group.key === key) {
      return group;
    }
    for (const item of group.items || []) {
      if (item.key === key) {
        return item;
      }
    }
  }
  return null;
}
