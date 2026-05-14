use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DesktopOrganizeOperation {
    pub file_name: String,
    pub from_path: String,
    pub to_path: String,
    pub category: String,
    pub category_label: String,
    pub target_folder: String,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DesktopOrganizeSkip {
    pub file_name: String,
    pub path: String,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopOrganizePreview {
    pub desktop_path: String,
    pub planned: Vec<DesktopOrganizeOperation>,
    pub skipped: Vec<DesktopOrganizeSkip>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopOrganizeApplyResult {
    pub moved: Vec<DesktopOrganizeOperation>,
    pub skipped: Vec<DesktopOrganizeSkip>,
    pub undo_available: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DesktopOrganizeRunResult {
    pub moved_count: usize,
    pub skipped_count: usize,
    pub arranged_icons: bool,
    pub undo_available: bool,
    pub skipped_reasons: Vec<String>,
    pub message: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopOrganizeUndoResult {
    pub restored: Vec<DesktopOrganizeOperation>,
    pub skipped: Vec<DesktopOrganizeSkip>,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DesktopIconArrangeResult {
    pub arranged: bool,
    pub message: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct UndoRecord {
    created_at: u64,
    desktop_path: String,
    moved: Vec<DesktopOrganizeOperation>,
}

struct RunOrganizeOutcome {
    result: DesktopOrganizeRunResult,
    moved: Vec<DesktopOrganizeOperation>,
}

#[derive(Clone, Copy)]
enum Locale {
    Zh,
    En,
}

impl Locale {
    fn from_opt(locale: Option<String>) -> Self {
        match locale.as_deref() {
            Some("en") => Self::En,
            _ => Self::Zh,
        }
    }
}

struct Category {
    id: &'static str,
    zh_label: &'static str,
    en_label: &'static str,
    zh_folder: &'static str,
    en_folder: &'static str,
}

impl Category {
    fn label(&self, locale: Locale) -> &'static str {
        match locale {
            Locale::Zh => self.zh_label,
            Locale::En => self.en_label,
        }
    }

    fn folder(&self, locale: Locale) -> &'static str {
        match locale {
            Locale::Zh => self.zh_folder,
            Locale::En => self.en_folder,
        }
    }
}

const IMAGES: Category = Category {
    id: "images",
    zh_label: "图片",
    en_label: "Images",
    zh_folder: "图片",
    en_folder: "Images",
};
const DOCUMENTS: Category = Category {
    id: "documents",
    zh_label: "文档",
    en_label: "Documents",
    zh_folder: "文档",
    en_folder: "Documents",
};
const SHEETS: Category = Category {
    id: "spreadsheets",
    zh_label: "表格",
    en_label: "Spreadsheets",
    zh_folder: "表格",
    en_folder: "Spreadsheets",
};
const PRESENTATIONS: Category = Category {
    id: "presentations",
    zh_label: "演示文稿",
    en_label: "Presentations",
    zh_folder: "演示文稿",
    en_folder: "Presentations",
};
const ARCHIVES: Category = Category {
    id: "archives",
    zh_label: "压缩包",
    en_label: "Archives",
    zh_folder: "压缩包",
    en_folder: "Archives",
};
const INSTALLERS: Category = Category {
    id: "installers",
    zh_label: "安装包",
    en_label: "Installers",
    zh_folder: "安装包",
    en_folder: "Installers",
};
const MEDIA: Category = Category {
    id: "media",
    zh_label: "音视频",
    en_label: "Media",
    zh_folder: "音视频",
    en_folder: "Media",
};
const CODE: Category = Category {
    id: "code",
    zh_label: "代码",
    en_label: "Code",
    zh_folder: "代码",
    en_folder: "Code",
};
const OTHER: Category = Category {
    id: "other",
    zh_label: "其他",
    en_label: "Other",
    zh_folder: "其他",
    en_folder: "Other",
};

fn category_for(ext: &str) -> &'static Category {
    match ext {
        "jpg" | "jpeg" | "png" | "gif" | "webp" | "bmp" | "svg" | "heic" | "avif" => &IMAGES,
        "pdf" | "doc" | "docx" | "txt" | "md" | "rtf" | "epub" => &DOCUMENTS,
        "xls" | "xlsx" | "xlsm" | "csv" | "tsv" => &SHEETS,
        "ppt" | "pptx" | "key" => &PRESENTATIONS,
        "zip" | "7z" | "rar" | "tar" | "gz" | "bz2" => &ARCHIVES,
        "exe" | "msi" | "msix" | "appx" => &INSTALLERS,
        "mp3" | "wav" | "m4a" | "flac" | "mp4" | "mov" | "avi" | "mkv" | "webm" => &MEDIA,
        "js" | "ts" | "tsx" | "jsx" | "py" | "rs" | "go" | "java" | "cs" | "json" | "yaml"
        | "yml" | "html" | "css" | "sql" => &CODE,
        _ => &OTHER,
    }
}

fn is_shortcut_or_system_name(file_name: &str) -> bool {
    let lower = file_name.to_ascii_lowercase();
    lower == "desktop.ini"
        || lower.ends_with(".lnk")
        || lower.ends_with(".url")
        || lower.ends_with(".website")
}

#[cfg(windows)]
fn has_hidden_or_system_attrs(meta: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_HIDDEN: u32 = 0x2;
    const FILE_ATTRIBUTE_SYSTEM: u32 = 0x4;
    let attrs = meta.file_attributes();
    attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM) != 0
}

#[cfg(not(windows))]
fn has_hidden_or_system_attrs(_meta: &fs::Metadata) -> bool {
    false
}

fn is_inside(root: &Path, candidate: &Path) -> bool {
    let root = match root.canonicalize() {
        Ok(p) => p,
        Err(_) => return false,
    };
    let candidate = if candidate.exists() {
        match candidate.canonicalize() {
            Ok(p) => p,
            Err(_) => return false,
        }
    } else {
        match candidate.parent().and_then(|p| p.canonicalize().ok()) {
            Some(parent) => match candidate.file_name() {
                Some(name) => parent.join(name),
                None => return false,
            },
            None => return false,
        }
    };
    candidate.starts_with(root)
}

fn arrange_success_message(locale: Locale) -> &'static str {
    match locale {
        Locale::Zh => "桌面图标已重新对齐到网格。",
        Locale::En => "Desktop icons were aligned to the grid.",
    }
}

#[cfg(not(windows))]
fn arrange_desktop_icons(locale: Locale) -> Result<DesktopIconArrangeResult, String> {
    let _ = locale;
    Err("整理桌面图标目前只支持 Windows。".to_string())
}

#[cfg(windows)]
fn arrange_desktop_icons(locale: Locale) -> Result<DesktopIconArrangeResult, String> {
    type Hwnd = isize;
    const LVM_FIRST: u32 = 0x1000;
    const LVM_ARRANGE: u32 = LVM_FIRST + 22;
    const LVA_DEFAULT: usize = 0;

    #[link(name = "user32")]
    extern "system" {
        fn FindWindowW(class_name: *const u16, window_name: *const u16) -> Hwnd;
        fn FindWindowExW(
            parent: Hwnd,
            child_after: Hwnd,
            class_name: *const u16,
            window_name: *const u16,
        ) -> Hwnd;
        fn EnumWindows(
            callback: Option<unsafe extern "system" fn(Hwnd, isize) -> i32>,
            lparam: isize,
        ) -> i32;
        fn SendMessageW(hwnd: Hwnd, msg: u32, wparam: usize, lparam: isize) -> isize;
    }

    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(std::iter::once(0)).collect()
    }

    unsafe fn find_listview_under(parent: Hwnd) -> Hwnd {
        let shell_class = wide("SHELLDLL_DefView");
        let list_class = wide("SysListView32");
        let shell = FindWindowExW(parent, 0, shell_class.as_ptr(), std::ptr::null());
        if shell == 0 {
            return 0;
        }
        FindWindowExW(shell, 0, list_class.as_ptr(), std::ptr::null())
    }

    struct EnumData {
        listview: Hwnd,
    }

    unsafe extern "system" fn enum_windows_proc(hwnd: Hwnd, lparam: isize) -> i32 {
        let data = &mut *(lparam as *mut EnumData);
        let worker_class = wide("WorkerW");
        let is_worker = FindWindowExW(hwnd, 0, worker_class.as_ptr(), std::ptr::null()) == 0;
        let listview = if is_worker {
            find_listview_under(hwnd)
        } else {
            0
        };
        if listview != 0 {
            data.listview = listview;
            0
        } else {
            1
        }
    }

    unsafe {
        let progman_class = wide("Progman");
        let progman = FindWindowW(progman_class.as_ptr(), std::ptr::null());
        let mut listview = if progman != 0 {
            find_listview_under(progman)
        } else {
            0
        };

        if listview == 0 {
            let mut data = EnumData { listview: 0 };
            EnumWindows(Some(enum_windows_proc), &mut data as *mut EnumData as isize);
            listview = data.listview;
        }

        if listview == 0 {
            return Err("没有找到 Windows 桌面图标视图。".to_string());
        }

        SendMessageW(listview, LVM_ARRANGE, LVA_DEFAULT, 0);
    }

    Ok(DesktopIconArrangeResult {
        arranged: true,
        message: arrange_success_message(locale).to_string(),
    })
}

#[cfg(test)]
mod arrange_tests {
    use super::*;

    #[test]
    fn arrange_success_message_uses_locale() {
        assert_eq!(
            arrange_success_message(Locale::Zh),
            "桌面图标已重新对齐到网格。"
        );
        assert_eq!(
            arrange_success_message(Locale::En),
            "Desktop icons were aligned to the grid."
        );
    }
}

fn build_plan(desktop: &Path, locale: Locale) -> Result<DesktopOrganizePreview, String> {
    if !desktop.is_dir() {
        return Err(format!("desktop is not a directory: {}", desktop.display()));
    }

    let mut planned = Vec::new();
    let mut skipped = Vec::new();
    let entries = fs::read_dir(desktop).map_err(|e| format!("read desktop: {e}"))?;

    for entry in entries {
        let entry = match entry {
            Ok(e) => e,
            Err(e) => {
                skipped.push(DesktopOrganizeSkip {
                    file_name: "(unknown)".to_string(),
                    path: desktop.display().to_string(),
                    reason: format!("无法读取：{e}"),
                });
                continue;
            }
        };
        let path = entry.path();
        let file_name = entry.file_name().to_string_lossy().to_string();
        let meta = match entry.metadata() {
            Ok(m) => m,
            Err(e) => {
                skipped.push(DesktopOrganizeSkip {
                    file_name,
                    path: path.display().to_string(),
                    reason: format!("无法读取文件信息：{e}"),
                });
                continue;
            }
        };

        if !meta.is_file() {
            continue;
        }
        if file_name.starts_with('.') || is_shortcut_or_system_name(&file_name) {
            skipped.push(DesktopOrganizeSkip {
                file_name,
                path: path.display().to_string(),
                reason: "跳过快捷方式、隐藏入口或系统文件".to_string(),
            });
            continue;
        }
        if has_hidden_or_system_attrs(&meta) {
            skipped.push(DesktopOrganizeSkip {
                file_name,
                path: path.display().to_string(),
                reason: "跳过隐藏或系统文件".to_string(),
            });
            continue;
        }

        let ext = path
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let category = category_for(&ext);
        let target_folder = category.folder(locale).to_string();
        let dest = desktop.join(&target_folder).join(&file_name);

        if dest.exists() {
            skipped.push(DesktopOrganizeSkip {
                file_name,
                path: path.display().to_string(),
                reason: format!("目标文件已存在：{}", dest.display()),
            });
            continue;
        }

        planned.push(DesktopOrganizeOperation {
            file_name,
            from_path: path.display().to_string(),
            to_path: dest.display().to_string(),
            category: category.id.to_string(),
            category_label: category.label(locale).to_string(),
            target_folder,
        });
    }

    planned.sort_by(|a, b| {
        a.category
            .cmp(&b.category)
            .then_with(|| a.file_name.to_lowercase().cmp(&b.file_name.to_lowercase()))
    });
    skipped.sort_by(|a, b| a.file_name.to_lowercase().cmp(&b.file_name.to_lowercase()));

    Ok(DesktopOrganizePreview {
        desktop_path: desktop.display().to_string(),
        planned,
        skipped,
    })
}

fn validate_operation(
    desktop: &Path,
    op: &DesktopOrganizeOperation,
) -> Result<(PathBuf, PathBuf), String> {
    let from = PathBuf::from(&op.from_path);
    let to = PathBuf::from(&op.to_path);
    if !is_inside(desktop, &from) {
        return Err(format!("operation escapes desktop: {}", op.file_name));
    }
    if from.parent() != Some(desktop) {
        return Err(format!(
            "only top-level desktop files can be moved: {}",
            op.file_name
        ));
    }
    let desktop = desktop
        .canonicalize()
        .map_err(|e| format!("desktop path unavailable: {e}"))?;
    let target_root = to.parent().and_then(|p| p.parent()).ok_or_else(|| {
        format!(
            "target must be one category folder under desktop: {}",
            op.file_name
        )
    })?;
    let target_root = target_root
        .canonicalize()
        .map_err(|e| format!("target desktop path unavailable: {e}"))?;
    if target_root != desktop {
        return Err(format!(
            "target must be one category folder under desktop: {}",
            op.file_name
        ));
    }
    Ok((from, to))
}

fn apply_plan(
    desktop: &Path,
    operations: Vec<DesktopOrganizeOperation>,
) -> DesktopOrganizeApplyResult {
    let mut moved = Vec::new();
    let mut skipped = Vec::new();

    for op in operations {
        let (from, to) = match validate_operation(desktop, &op) {
            Ok(paths) => paths,
            Err(reason) => {
                skipped.push(DesktopOrganizeSkip {
                    file_name: op.file_name,
                    path: op.from_path,
                    reason,
                });
                continue;
            }
        };
        if !from.is_file() {
            skipped.push(DesktopOrganizeSkip {
                file_name: op.file_name,
                path: from.display().to_string(),
                reason: "源文件不存在或不是文件".to_string(),
            });
            continue;
        }
        if to.exists() {
            skipped.push(DesktopOrganizeSkip {
                file_name: op.file_name,
                path: from.display().to_string(),
                reason: "目标文件已存在，未覆盖".to_string(),
            });
            continue;
        }
        if let Some(parent) = to.parent() {
            if let Err(e) = fs::create_dir_all(parent) {
                skipped.push(DesktopOrganizeSkip {
                    file_name: op.file_name,
                    path: parent.display().to_string(),
                    reason: format!("无法创建目标文件夹：{e}"),
                });
                continue;
            }
        }
        match fs::rename(&from, &to) {
            Ok(()) => moved.push(op),
            Err(e) => skipped.push(DesktopOrganizeSkip {
                file_name: op.file_name,
                path: from.display().to_string(),
                reason: format!("移动失败：{e}"),
            }),
        }
    }

    DesktopOrganizeApplyResult {
        undo_available: !moved.is_empty(),
        moved,
        skipped,
    }
}

fn skipped_reason_text(skip: &DesktopOrganizeSkip) -> String {
    format!("{}: {}", skip.file_name, skip.reason)
}

fn run_summary_message(
    locale: Locale,
    moved_count: usize,
    skipped_count: usize,
    arranged_icons: bool,
) -> String {
    match locale {
        Locale::Zh => {
            let mut parts = Vec::new();
            if moved_count > 0 {
                parts.push(format!("已归类 {moved_count} 个文件"));
            }
            if skipped_count > 0 {
                parts.push(format!("{skipped_count} 个因同名文件或不适合移动而跳过"));
            }
            if arranged_icons {
                parts.push("桌面图标已排列整齐".to_string());
            }
            if parts.is_empty() {
                "整理好了：桌面已经很整齐。".to_string()
            } else {
                format!("整理好了：{}。", parts.join("，"))
            }
        }
        Locale::En => {
            let mut parts = Vec::new();
            if moved_count > 0 {
                parts.push(format!("organized {moved_count} files"));
            }
            if skipped_count > 0 {
                parts.push(format!("skipped {skipped_count} files"));
            }
            if arranged_icons {
                parts.push("arranged desktop icons".to_string());
            }
            if parts.is_empty() {
                "Done: your desktop was already tidy.".to_string()
            } else {
                format!("Done: {}.", parts.join(", "))
            }
        }
    }
}

fn run_organize_internal(
    desktop: &Path,
    locale: Locale,
    arrange_icons: bool,
) -> Result<RunOrganizeOutcome, String> {
    let preview = build_plan(desktop, locale)?;
    let preview_skipped = preview.skipped;
    let apply_result = apply_plan(desktop, preview.planned);
    let moved_count = apply_result.moved.len();
    let skipped_count = preview_skipped.len() + apply_result.skipped.len();
    let mut skipped_reasons: Vec<String> = preview_skipped
        .iter()
        .chain(apply_result.skipped.iter())
        .map(skipped_reason_text)
        .collect();

    let arranged_icons = if arrange_icons {
        match arrange_desktop_icons(locale) {
            Ok(result) => result.arranged,
            Err(reason) => {
                skipped_reasons.push(reason);
                false
            }
        }
    } else {
        false
    };

    let result = DesktopOrganizeRunResult {
        moved_count,
        skipped_count,
        arranged_icons,
        undo_available: !apply_result.moved.is_empty(),
        skipped_reasons,
        message: run_summary_message(locale, moved_count, skipped_count, arranged_icons),
    };

    Ok(RunOrganizeOutcome {
        result,
        moved: apply_result.moved,
    })
}

fn run_organize(
    desktop: &Path,
    locale: Locale,
    arrange_icons: bool,
) -> Result<DesktopOrganizeRunResult, String> {
    run_organize_internal(desktop, locale, arrange_icons).map(|outcome| outcome.result)
}

fn undo_record_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = crate::paths::ensure_data_dir(app)
        .map_err(|e| e.to_string())?
        .join("desktop-organizer");
    fs::create_dir_all(&dir).map_err(|e| format!("create undo dir: {e}"))?;
    Ok(dir.join("last_undo.json"))
}

fn write_undo_record(
    app: &AppHandle,
    desktop: &Path,
    moved: &[DesktopOrganizeOperation],
) -> Result<(), String> {
    let record = UndoRecord {
        created_at: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
        desktop_path: desktop.display().to_string(),
        moved: moved.to_vec(),
    };
    let path = undo_record_path(app)?;
    let raw = serde_json::to_vec_pretty(&record).map_err(|e| e.to_string())?;
    fs::write(&path, raw).map_err(|e| format!("write undo record: {e}"))
}

fn desktop_dir(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .desktop_dir()
        .map_err(|e| format!("desktop dir: {e}"))
}

#[tauri::command]
pub fn cmd_desktop_organize_preview(
    app: AppHandle,
    locale: Option<String>,
) -> Result<DesktopOrganizePreview, String> {
    let desktop = desktop_dir(&app)?;
    build_plan(&desktop, Locale::from_opt(locale))
}

#[tauri::command]
pub fn cmd_desktop_organize_apply(
    app: AppHandle,
    operations: Vec<DesktopOrganizeOperation>,
) -> Result<DesktopOrganizeApplyResult, String> {
    let desktop = desktop_dir(&app)?;
    let result = apply_plan(&desktop, operations);
    if !result.moved.is_empty() {
        write_undo_record(&app, &desktop, &result.moved)?;
    }
    Ok(result)
}

#[tauri::command]
pub fn cmd_desktop_organize_run(
    app: AppHandle,
    locale: Option<String>,
) -> Result<DesktopOrganizeRunResult, String> {
    let desktop = desktop_dir(&app)?;
    let outcome = run_organize_internal(&desktop, Locale::from_opt(locale), true)?;
    if !outcome.moved.is_empty() {
        write_undo_record(&app, &desktop, &outcome.moved)?;
    }
    Ok(outcome.result)
}

#[tauri::command]
pub fn cmd_desktop_organize_undo(app: AppHandle) -> Result<DesktopOrganizeUndoResult, String> {
    let path = undo_record_path(&app)?;
    let raw = fs::read_to_string(&path).map_err(|_| "没有可撤销的桌面整理记录。".to_string())?;
    let record: UndoRecord =
        serde_json::from_str(&raw).map_err(|e| format!("read undo record: {e}"))?;
    let desktop = PathBuf::from(&record.desktop_path);
    let mut restored = Vec::new();
    let mut skipped = Vec::new();

    for op in record.moved.into_iter().rev() {
        let original = PathBuf::from(&op.from_path);
        let current = PathBuf::from(&op.to_path);
        if !is_inside(&desktop, &original) || !is_inside(&desktop, &current) {
            skipped.push(DesktopOrganizeSkip {
                file_name: op.file_name,
                path: op.to_path,
                reason: "撤销路径不在桌面范围内".to_string(),
            });
            continue;
        }
        if !current.is_file() {
            skipped.push(DesktopOrganizeSkip {
                file_name: op.file_name,
                path: current.display().to_string(),
                reason: "整理后的文件不存在，未撤销".to_string(),
            });
            continue;
        }
        if original.exists() {
            skipped.push(DesktopOrganizeSkip {
                file_name: op.file_name,
                path: original.display().to_string(),
                reason: "原位置已有同名文件，未覆盖".to_string(),
            });
            continue;
        }
        match fs::rename(&current, &original) {
            Ok(()) => restored.push(op),
            Err(e) => skipped.push(DesktopOrganizeSkip {
                file_name: op.file_name,
                path: current.display().to_string(),
                reason: format!("撤销失败：{e}"),
            }),
        }
    }
    if !restored.is_empty() {
        let _ = fs::remove_file(path);
    }
    Ok(DesktopOrganizeUndoResult { restored, skipped })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_desktop(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "kabuqina-desktop-organizer-{name}-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    #[test]
    fn preview_groups_top_level_files_and_skips_shortcuts_hidden_entries_and_folders() {
        let desktop = temp_desktop("preview");
        fs::write(desktop.join("photo.png"), "x").unwrap();
        fs::write(desktop.join("report.pdf"), "x").unwrap();
        fs::write(desktop.join("setup.exe"), "x").unwrap();
        fs::write(desktop.join("app.lnk"), "x").unwrap();
        fs::write(desktop.join(".secret.txt"), "x").unwrap();
        fs::write(desktop.join("desktop.ini"), "x").unwrap();
        fs::create_dir_all(desktop.join("folder")).unwrap();

        let preview = build_plan(&desktop, Locale::Zh).unwrap();

        let planned: Vec<_> = preview
            .planned
            .iter()
            .map(|op| (op.file_name.as_str(), op.target_folder.as_str()))
            .collect();
        assert_eq!(
            planned,
            vec![
                ("report.pdf", "文档"),
                ("photo.png", "图片"),
                ("setup.exe", "安装包")
            ]
        );
        let skipped: Vec<_> = preview
            .skipped
            .iter()
            .map(|skip| skip.file_name.as_str())
            .collect();
        assert_eq!(skipped, vec![".secret.txt", "app.lnk", "desktop.ini"]);

        let _ = fs::remove_dir_all(desktop);
    }

    #[test]
    fn preview_skips_when_target_exists() {
        let desktop = temp_desktop("conflict");
        fs::write(desktop.join("photo.png"), "x").unwrap();
        fs::create_dir_all(desktop.join("图片")).unwrap();
        fs::write(desktop.join("图片").join("photo.png"), "existing").unwrap();

        let preview = build_plan(&desktop, Locale::Zh).unwrap();

        assert!(preview.planned.is_empty());
        assert_eq!(preview.skipped.len(), 1);
        assert!(preview.skipped[0].reason.contains("目标文件已存在"));

        let _ = fs::remove_dir_all(desktop);
    }

    #[test]
    fn apply_moves_only_valid_desktop_operations() {
        let desktop = temp_desktop("apply");
        let outside = temp_desktop("outside");
        fs::write(desktop.join("photo.png"), "x").unwrap();
        fs::write(outside.join("escape.txt"), "x").unwrap();
        let valid = DesktopOrganizeOperation {
            file_name: "photo.png".to_string(),
            from_path: desktop.join("photo.png").display().to_string(),
            to_path: desktop.join("图片").join("photo.png").display().to_string(),
            category: "images".to_string(),
            category_label: "图片".to_string(),
            target_folder: "图片".to_string(),
        };
        let invalid = DesktopOrganizeOperation {
            file_name: "escape.txt".to_string(),
            from_path: outside.join("escape.txt").display().to_string(),
            to_path: desktop
                .join("文档")
                .join("escape.txt")
                .display()
                .to_string(),
            category: "documents".to_string(),
            category_label: "文档".to_string(),
            target_folder: "文档".to_string(),
        };

        let result = apply_plan(&desktop, vec![valid, invalid]);

        assert_eq!(result.moved.len(), 1);
        assert_eq!(result.skipped.len(), 1);
        assert!(desktop.join("图片").join("photo.png").is_file());
        assert!(outside.join("escape.txt").is_file());

        let _ = fs::remove_dir_all(desktop);
        let _ = fs::remove_dir_all(outside);
    }

    #[test]
    fn run_organize_moves_files_and_returns_summary() {
        let desktop = temp_desktop("run");
        fs::write(desktop.join("photo.png"), "x").unwrap();
        fs::write(desktop.join("notes.txt"), "x").unwrap();
        fs::write(desktop.join("app.lnk"), "x").unwrap();

        let result = run_organize(&desktop, Locale::Zh, false).unwrap();

        assert_eq!(result.moved_count, 2);
        assert_eq!(result.skipped_count, 1);
        assert!(!result.arranged_icons);
        assert!(result.undo_available);
        assert!(result.message.contains("已归类 2 个文件"));
        assert!(desktop.join("图片").join("photo.png").is_file());
        assert!(desktop.join("文档").join("notes.txt").is_file());
        assert!(desktop.join("app.lnk").is_file());

        let _ = fs::remove_dir_all(desktop);
    }
}
