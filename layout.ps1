# layout.ps1 — arrange 4 visible demo windows in a 2x2 grid by fixed coordinates.
# DPI-unaware: all coordinates are in logical 96-DPI pixels (matches what the
# user sees under Windows scaling, e.g. 2880x1800 @200% -> 1440x900 logical).
# Server runs hidden (pythonw) and is NOT arranged.
$ErrorActionPreference = 'SilentlyContinue'

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WinApi {
    [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int value);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint dwFlags);
    [DllImport("user32.dll")] public static extern bool GetMonitorInfo(IntPtr hMonitor, ref MONITORINFO lpmi);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct MONITORINFO {
        public int cbSize; public RECT rcMonitor, rcWork; public uint dwFlags;
    }
}
"@ | Out-Null

# 0 = PROCESS_DPI_UNAWARE -> Windows virtualizes coords to 96-DPI logical pixels.
[WinApi]::SetProcessDpiAwareness(0) | Out-Null

# --- find primary monitor work area (logical pixels) ---
$mi = New-Object WinApi+MONITORINFO
$mi.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($mi)
$hMon = [WinApi]::MonitorFromWindow([WinApi]::GetForegroundWindow(), 1)
[WinApi]::GetMonitorInfo($hMon, [ref]$mi) | Out-Null
$wa = $mi.rcWork
$monX = [int]$wa.Left; $monY = [int]$wa.Top
$monW = [int]($wa.Right - $wa.Left); $monH = [int]($wa.Bottom - $wa.Top)

# --- find the 4 visible demo windows by title OR class ---
$Script:Found = @{}
$enum = [WinApi+EnumWindowsProc]{
    param($hwnd, $lp)
    if (-not [WinApi]::IsWindowVisible($hwnd)) { return $true }
    $title = New-Object System.Text.StringBuilder 512
    [WinApi]::GetWindowText($hwnd, $title, 512) | Out-Null
    $cls = New-Object System.Text.StringBuilder 256
    [WinApi]::GetClassName($hwnd, $cls, 256) | Out-Null
    $t = $title.ToString(); $c = $cls.ToString()
    if ($t.StartsWith("STAT_WATCHER")) { $Script:Found['W'] = $hwnd }
    elseif ($t.StartsWith("STAT_GEN")) { $Script:Found['G'] = $hwnd }
    elseif ($c -eq 'CabinetWClass' -and $t -match 'test_reports') { $Script:Found['E'] = $hwnd }
    # DEFAULT browser (no hard Firefox dependency): match by URL in title OR
    # by any known browser window class. Covers Chrome/Edge/Firefox/Opera/brave.
    # Use -match (regex) so both "127.0.0.1:8770" and "127.0.0.1/8770" titles hit.
    elseif ($t -match '127\.0\.0\.1[:/]?8770' -or
            $c -match 'MozillaWindowClass|Chrome_WidgetWin_1|MsEdge_WidgetWin_1|ApplicationFrameWindow|OpWindow') {
        if (-not $Script:Found['F']) { $Script:Found['F'] = $hwnd }
    }
    return $true
}
[WinApi]::EnumWindows($enum, [IntPtr]::Zero) | Out-Null
$wins = $Script:Found

# --- 2x2 grid (logical pixels, relative to work area) ---
$gap   = 8
$colW  = [int](($monW - 3*$gap) / 2)
$rowH  = [int](($monH - 3*$gap) / 2)
$leftX = [int]($monX + $gap)
$rightX = [int]($monX + $gap + $colW + $gap)
$topY  = [int]($monY + $gap)
$botY  = [int]($monY + $gap + $rowH + $gap)

$SWP_SHOWWINDOW = 0x0040
$SWP_FRAMECHANGED = 0x0020
$SW_RESTORE = 9
function Place($hwnd, $x, $y, $w, $h) {
    if ($hwnd) {
        [WinApi]::ShowWindow($hwnd, $SW_RESTORE) | Out-Null
        [WinApi]::SetWindowPos($hwnd, [IntPtr]::Zero, $x, $y, $w, $h, ($SWP_SHOWWINDOW -bor $SWP_FRAMECHANGED)) | Out-Null
    }
}

# top-left: explorer | top-right: watcher
Place $wins.E  $leftX  $topY   $colW  $rowH
Place $wins.W  $rightX $topY   $colW  $rowH
# bottom-left: firefox | bottom-right: generator
Place $wins.F  $leftX  $botY   $colW  $rowH
Place $wins.G  $rightX $botY   $colW  $rowH

Write-Host "layout.ps1: windows arranged (monitor ${monW}x${monH}, logical, 2x2 grid)."
