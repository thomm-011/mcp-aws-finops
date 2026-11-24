Output docs/demo.gif

Set Shell "bash"
Set FontSize 16
Set Width 1000
Set Height 600
Set WaitPattern />\s*$/
Set Padding 10
Set TypingSpeed 35ms
Set Theme "Dracula"

Type "export PATH=$HOME/.local/bin:$PATH; clear"
Enter
Sleep 500ms

Type `hermes -p finops-demo -t aws-finops -z "Which service drove the cost spike on 2025-08-25?"`
Enter
Wait@120s
Sleep 4s

Type `hermes -p finops-demo -t aws-finops -z "Break down cost by team tag for August 2025, with % untagged"`
Enter
Wait@120s
Sleep 4s
