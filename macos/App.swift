import AppKit
import WebKit

final class QueueApp: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    let address = URL(string: "http://127.0.0.1:8787/")!
    var window: NSWindow!
    var web: WKWebView!
    var starting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let appMenu = NSMenu()
        let item = NSMenuItem()
        let submenu = NSMenu()
        submenu.addItem(withTitle: "退出候场", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = submenu
        appMenu.addItem(item)
        let viewItem = NSMenuItem()
        let view = NSMenu(title: "查看")
        let reload = view.addItem(withTitle: "重新连接", action: #selector(connect), keyEquivalent: "r")
        reload.target = self
        viewItem.submenu = view
        appMenu.addItem(viewItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "编辑")
        for (title, action, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"),
                                      ("复制", "copy:", "c"), ("粘贴", "paste:", "v"),
                                      ("全选", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editItem.submenu = edit
        appMenu.insertItem(editItem, at: 1)
        NSApp.mainMenu = appMenu

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1140, height: 770),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: .darkAqua)
        window.title = "候场 · Codex 任务队列"
        window.minSize = NSSize(width: 390, height: 480)
        web = WKWebView()
        web.navigationDelegate = self
        window.contentView = web
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        connect()
    }

    @objc func connect() {
        guard !starting else { return }
        starting = true
        web.loadHTMLString("<meta charset=utf-8><p style='font:16px system-ui;padding:24px'>正在启动任务队列…</p>", baseURL: nil)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", Bundle.main.resourceURL!.appendingPathComponent("queue/launcher.py").path, "--no-open"]
        var environment = ProcessInfo.processInfo.environment
        let paths = [NSHomeDirectory() + "/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/Library/Frameworks/Python.framework/Versions/Current/bin", "/usr/bin", "/bin"]
        environment["PATH"] = (paths + [environment["PATH"] ?? ""]).joined(separator: ":")
        process.environment = environment
        process.terminationHandler = { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.starting = false
                if result.terminationStatus == 0 {
                    self.web.load(URLRequest(url: self.address, cachePolicy: .reloadIgnoringLocalCacheData))
                } else {
                    self.showError()
                }
            }
        }
        do { try process.run() } catch {
            starting = false
            showError()
        }
    }

    func showError() {
        web.loadHTMLString("""
        <meta charset=utf-8><main style='font:16px system-ui;padding:24px'>
        <h2>无法连接任务队列</h2>
        <p>请检查 Python 3、Codex CLI 和本机登录状态，再按 ⌘R 重试。</p>
        <p>后台日志位于 ~/Library/Application Support/task-queue-codex/service.log。</p>
        </main>
        """, baseURL: nil)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        let local = url.scheme == "http" && url.host == "127.0.0.1" && url.port == 8787
        decisionHandler(local || url.absoluteString == "about:blank" ? .allow : .cancel)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

let application = NSApplication.shared
let delegate = QueueApp()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
