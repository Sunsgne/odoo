import { useEffect, useState } from "react";
import { Box, Button, Card, CardContent, Checkbox, Dialog, DialogContent, DialogTitle, FormControlLabel, Typography } from "@mui/material";
import { call } from "../api";

export function DutyPage() {
  const [board, setBoard] = useState(null);
  const [cell, setCell] = useState(null);

  async function load(anchor) {
    setBoard(await call("zenlenet.duty.sheet", "calendar", [], {
      sheet_id: board?.sheet_id || false,
      anchor: anchor || board?.anchor || false,
      mode: board?.mode || "week",
    }));
  }

  useEffect(() => { load().catch(() => {}); }, []);

  async function openCell(shift) {
    if (!shift.cell_id) {
      return;
    }
    setCell(await call("zenlenet.duty.cell", "detail", [[shift.cell_id]]));
  }

  async function toggle(person) {
    await call("zenlenet.duty.cell", "set_member", [[cell.cell_id], person.id, !person.on]);
    setCell(await call("zenlenet.duty.cell", "detail", [[cell.cell_id]]));
    await load();
  }

  if (!board) {
    return null;
  }
  const weeks = [];
  for (let index = 0; index < (board.days || []).length; index += 7) {
    weeks.push(board.days.slice(index, index + 7));
  }

  return (
    <Box>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", mb: 2 }}>
        {(board.sheets || []).map((sheet) => (
          <Button key={sheet.id} variant={board.sheet_id === sheet.id ? "contained" : "outlined"} onClick={() => { board.sheet_id = sheet.id; load(); }}>{sheet.name}</Button>
        ))}
        <Button variant="outlined" onClick={() => load(shiftAnchor(board.anchor, board.mode, -1))}>上一页</Button>
        <Button variant="outlined" onClick={() => load(shiftAnchor(board.anchor, board.mode, 1))}>下一页</Button>
        <Button variant={board.mode === "week" ? "contained" : "outlined"} onClick={() => { board.mode = "week"; load(); }}>周</Button>
        <Button variant={board.mode === "month" ? "contained" : "outlined"} onClick={() => { board.mode = "month"; load(); }}>月</Button>
      </Box>
      {weeks.map((week) => (
        <Box key={week[0]?.date} sx={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(160px, 1fr))", gap: 1, mb: 2 }}>
          {week.map((column) => (
            <Card key={column.date} sx={{ opacity: column.in_month ? 1 : 0.45 }}>
              <CardContent sx={{ p: 1.5 }}>
                <Typography variant="subtitle2">{column.weekday} {column.date}{column.today ? " 今天" : ""}</Typography>
                {(column.regions || []).map((region) => (
                  <Box key={region.id} sx={{ mt: 1 }}>
                    <Typography variant="caption" color="text.secondary">{region.name} {region.offset}</Typography>
                    {(region.shifts || []).map((shift) => (
                      <Box key={shift.cell_id || shift.shift_id} onClick={() => openCell(shift)} sx={{ bgcolor: shift.kind === "night" ? "primary.50" : "grey.100", borderRadius: 1, p: 0.75, mt: 0.5, cursor: "pointer", outline: shift.short ? "1px solid #ed6c02" : "none" }}>
                        <Typography variant="body2">{shift.name} {shift.filled}/{shift.need}</Typography>
                        <Typography variant="caption">{shift.start} → {shift.end}{shift.overnight ? " +1d" : ""}</Typography>
                        <Typography variant="caption" display="block">{(shift.people || []).map((person) => person.name).join(" ")}</Typography>
                      </Box>
                    ))}
                  </Box>
                ))}
              </CardContent>
            </Card>
          ))}
        </Box>
      ))}
      <Dialog open={Boolean(cell)} onClose={() => setCell(null)}>
        <DialogTitle>{cell?.name} {cell?.date}</DialogTitle>
        <DialogContent>
          {(cell?.people || []).map((person) => (
            <FormControlLabel key={person.id} control={<Checkbox checked={person.on} onChange={() => toggle(person)} />} label={person.name} />
          ))}
        </DialogContent>
      </Dialog>
    </Box>
  );
}

function shiftAnchor(anchor, mode, step) {
  const day = anchor ? new Date(`${anchor}T00:00:00`) : new Date();
  if (mode === "month") {
    day.setMonth(day.getMonth() + step, 1);
  } else {
    day.setDate(day.getDate() + step * 7);
  }
  const month = String(day.getMonth() + 1).padStart(2, "0");
  const date = String(day.getDate()).padStart(2, "0");
  return `${day.getFullYear()}-${month}-${date}`;
}
