import { useEffect, useState } from "react";
import { Box, Tab, Tabs } from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";
import { call } from "../api";

const TABS = [
  ["plan", "采购计划"],
  ["expected", "设备入库"],
  ["inbound", "设备签收"],
  ["signed", "采购验收"],
];

export function PurchasePage({ navigate }) {
  const [tab, setTab] = useState("plan");
  const [rows, setRows] = useState([]);

  async function load(next = tab) {
    if (next === "plan") {
      setRows(await call("zenlenet.purchase", "plan_rows", [""]));
    } else {
      setRows(await call("zenlenet.purchase.device", "queue_rows", [next, ""]));
    }
  }

  useEffect(() => { load().catch(() => {}); }, [tab]);

  const columns = tab === "plan"
    ? [
      { field: "name", headerName: "计划编号", flex: 1 },
      { field: "resource", headerName: "计划名称", flex: 1.4 },
      { field: "contract_code", headerName: "合同编号", flex: 1 },
      { field: "devices", headerName: "设备数量", width: 110 },
      { field: "state_label", headerName: "状态", width: 110 },
      { field: "created", headerName: "创建时间", flex: 1 },
    ]
    : [
      { field: "sn", headerName: "资产序列号", flex: 1 },
      { field: "plan", headerName: "计划", flex: 1 },
      { field: "category", headerName: "类型", width: 120 },
      { field: "model", headerName: "型号", flex: 1 },
      { field: "maker", headerName: "厂商", width: 120 },
      { field: "state_label", headerName: "状态", width: 110 },
    ];

  return (
    <Box>
      <Tabs value={tab} onChange={(_event, value) => setTab(value)} sx={{ mb: 2 }}>
        {TABS.map(([key, label]) => <Tab key={key} value={key} label={label} />)}
      </Tabs>
      <Box sx={{ height: 640, bgcolor: "background.paper" }}>
        <DataGrid rows={rows} columns={columns} disableRowSelectionOnClick pageSizeOptions={[25, 50]} initialState={{ pagination: { paginationModel: { pageSize: 25 } } }} />
      </Box>
    </Box>
  );
}
