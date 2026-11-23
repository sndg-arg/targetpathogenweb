import csv
import io
import re

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from django.http import HttpResponse

# Design system brand colors (from masterpage.html :root)
_XLSX_HEADER_BG = "F1F5F6"  # --tp-color-brand-050
_XLSX_HEADER_FG = "0F2F3A"  # --tp-color-brand-900
_XLSX_ALT_ROW = "F6F7F9"  # --tp-color-surface-soft
_XLSX_GROUP_BG = "E2EAED"  # --tp-color-brand-100
_XLSX_GROUP_BORDER = "A6BEC6"  # --tp-color-brand-300


def build_export_url(request, export_value="csv", strip_params=()):
    """URL for an export link/button: the current query string plus
    export=<export_value>. An identical @staticmethod (export=csv) was
    copy-pasted across ProteinListView, GenomesView and
    AnnotationExplorerView; all three now import this instead.
    `strip_params` covers ProteinListView's one behavioral difference (it
    also drops `page`, since a stale page number in the export link would
    silently limit the export to whatever page happened to be open)."""
    params = request.GET.copy()
    for name in strip_params:
        if name in params:
            params.pop(name)
    params["export"] = export_value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else f"?export={export_value}"


def build_view_export_url(request, strip_params=()):
    """URL for the "Export view" link/button: the current query string plus
    export=view_csv. An identical @staticmethod was copy-pasted across
    ProteinView, AssemblyView, AnnotationExplorerView and GenomesView; all
    four now import this instead."""
    return build_export_url(request, export_value="view_csv", strip_params=strip_params)


def _normalize_filename(value, fallback="export"):
    text = str(value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[^\w.-]+", "-", text, flags=re.ASCII).strip("-._")
    return text or fallback


def csv_response(filename_stem, headers, rows):
    filename = _normalize_filename(filename_stem)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return response


def xlsx_sections_response(filename_stem, sections):
    """
    Exports multi-section data as a formatted Excel workbook.
    Each section becomes a separate worksheet with styled headers. A section
    may also carry "header_groups" (one label per column, e.g. from
    export_columns.group_columns_by_block): runs of the same label get a
    merged band row above the headers.
    """
    filename = _normalize_filename(filename_stem)

    header_font = Font(bold=True, color=_XLSX_HEADER_FG)
    header_fill = PatternFill("solid", fgColor=_XLSX_HEADER_BG)
    alt_fill = PatternFill("solid", fgColor=_XLSX_ALT_ROW)
    group_fill = PatternFill("solid", fgColor=_XLSX_GROUP_BG)
    group_side = Side(style="thin", color=_XLSX_GROUP_BORDER)
    group_border = Border(left=group_side, right=group_side)
    center_align = Alignment(vertical="center")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    for section in sections:
        title = str(section.get("title") or "Data").strip() or "Data"
        headers = list(section.get("headers") or [])
        rows = list(section.get("rows") or [])

        groups = list(section.get("header_groups") or [])
        if len(groups) != len(headers):
            groups = []

        ws = wb.create_sheet(title=title[:31])

        col_widths = [max(len(str(h)), 6) for h in headers]

        header_row = 1
        if groups:
            ws.append(groups)
            start = 0
            for end in range(1, len(groups) + 1):
                if end == len(groups) or groups[end] != groups[start]:
                    if end - start > 1:
                        ws.merge_cells(
                            start_row=1, start_column=start + 1, end_row=1, end_column=end
                        )
                    start = end
            for cell in ws[1]:
                cell.font = header_font
                cell.fill = group_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = group_border
            ws.row_dimensions[1].height = 20
            header_row = 2

        if headers:
            ws.append(headers)
            for cell in ws[header_row]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center_align
            ws.row_dimensions[header_row].height = 22
            ws.freeze_panes = f"A{header_row + 1}"

        first_data_row = header_row + 1 if headers else header_row
        for row_num, row in enumerate(rows, first_data_row):
            normalized = ["" if v is None else v for v in row]
            ws.append(normalized)
            if (row_num - first_data_row) % 2 == 0:
                for cell in ws[row_num]:
                    cell.fill = alt_fill
            for col_idx, val in enumerate(normalized):
                if col_idx < len(col_widths):
                    col_widths[col_idx] = max(col_widths[col_idx], min(len(str(val)), 64))

        for col_idx, width in enumerate(col_widths, 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = width + 3

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response = HttpResponse(buffer.read(), content_type=mime)
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response
