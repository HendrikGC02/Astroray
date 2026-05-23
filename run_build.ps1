$ErrorActionPreference = "Continue"
& "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\build_cuda_worktree.bat" "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray-pkg64-gpu-sellmeier-upload" "33c2104" *>&1 | Tee-Object -FilePath "build_output.txt"
Write-Output "Exit code: $LASTEXITCODE"
