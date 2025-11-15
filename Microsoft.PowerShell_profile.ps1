function Set-TabTitle {
    $folder = Split-Path -Leaf (Get-Location)
    if ([string]::IsNullOrWhiteSpace($folder)) {
        $folder = "PowerShell"
    }
    $host.UI.RawUI.WindowTitle = $folder
}

# Update title whenever the prompt is rendered
function prompt {
    Set-TabTitle
    "PS " + $(Get-Location) + "> "
}

#VSCode's "code" shorthand
function co {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        $Args
    )

    code @Args
}

# Unix "open"
function open {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        $Args
    )

    explorer @Args
}

# Classic bash-style TAB completion (no menus, no lists, no right-arrow)
Set-PSReadLineOption -PredictionSource None
Set-PSReadLineKeyHandler -Key Tab -Function Complete
