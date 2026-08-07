(* layout_mac.scpt — arrange 4 demo windows in a 2x2 grid on macOS.
   Mirrors layout.ps1. Windows:
     - "test_reports" folder (Finder)
     - STAT_WATCHER terminal
     - default browser open at http://127.0.0.1:8770/
     - STAT_GEN terminal (generator)
   Finder + Terminal + Browser get tiled; uses the primary display's
   visible frame (minus menu bar / dock). *)

set gap to 8
set screenFrame to bounds of (do shell script "python3 -c \"import AppKit;f=AppKit.NSScreen.mainScreen.visibleFrame;print(f.origin.x,f.origin.y,f.size.width,f.size.height)\"")

-- parse "x y w h"
set {sx, sy, sw, sh} to my parse4(screenFrame)

set colW to (sw - 3 * gap) / 2
set rowH to (sh - 3 * gap) / 2
set leftX to sx + gap
set rightX to sx + gap + colW + gap
set topY to sy + gap
set botY to sy + gap + rowH + gap

my tileApp("Finder", "test_reports", leftX, topY, colW, rowH)
my tileTitle("STAT_WATCHER", rightX, topY, colW, rowH)
my tileBrowser("http://127.0.0.1:8770/", leftX, botY, colW, rowH)
my tileTitle("STAT_GEN", rightX, botY, colW, rowH)

on parse4(s)
    set out to {}
    repeat with w in (words of s)
        set end of out to w as number
    end repeat
    return out
end parse4

on tileApp(appName, winMatch, x, y, w, h)
    tell application appName
        try
            set i to 1
            repeat with win in windows
                if (name of win contains winMatch) then
                    set bounds of win to {x, y, x + w, y + h}
                    return
                end if
                set i to i + 1
            end repeat
        end try
    end tell
end tileApp

on tileTitle(titleMatch, x, y, w, h)
    tell application "System Events"
        repeat with p in (processes whose visible is true)
            try
                repeat with win in windows of p
                    if (name of win contains titleMatch) then
                        set bounds of win to {x, y, x + w, y + h}
                    end if
                end repeat
            end try
        end repeat
    end tell
end tileTitle

on tileBrowser(urlMatch, x, y, w, h)
    tell application "System Events"
        repeat with p in (processes whose visible is true)
            try
                set appName to name of p
                if appName is in {"Safari", "Google Chrome", "Firefox", "Microsoft Edge", "Arc", "Opera"} then
                    repeat with win in windows of p
                        if (name of win contains urlMatch) then
                            set bounds of win to {x, y, x + w, y + h}
                        end if
                    end repeat
                end if
            end try
        end repeat
    end tell
end tileBrowser
