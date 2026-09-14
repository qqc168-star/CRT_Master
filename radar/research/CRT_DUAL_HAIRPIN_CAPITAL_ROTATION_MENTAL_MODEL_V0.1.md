# CRT Dual Hairpin Capital Rotation Mental Model V0.1

## Status（狀態）

`NON_FORMAL_RESEARCH_ANCHOR`

## 一、定位

本文件保存雙釵滾金／資本輪動的可逆性心智模型。它回答的不是「哪一個收益率較高」，而是「賣出的每一單位核心資產，扣除實際摩擦並計入已可用現金後，能否完整買回」。

它是 GPT（分析主廚）的非正式研究檢查，不是正式模型、正式六層分數、燈號、價格閾值、交易 gate（關卡）或下單規則。Automation（自動化）可保存可驗證事實與重現計算；GPT（分析主廚）負責判讀；User（使用者）保有資本決策與所有外部行動權限。

本文件不保存短命報價、單期配息或當期股數。每次使用均須由當下 Evidence（證據）重新輸入實際市場與帳戶資料。

---

## 二、發行人健康不是自動加碼

分析發行人行動時，固定走以下鏈條：

`Fact -> Issuer Health -> Investor Risk -> Asset Role -> Portfolio Impact -> Capital Judgment`

（事實 → 發行人健康 → 投資人風險 → 資產角色 → 投資組合影響 → 資本判斷）

Risk Improvement（風險改善）不等於 Allocation Increase（配置增加）。信用、配息安全或流動性改善，首先可能提高既有部位 `HOLD`（續抱）的信心，形成 Risk-Budget Release（風險預算釋放）；新增資本仍須比較其他角色相容用途、集中度與現金選擇權。

發行人回購必須並列計算 Liability Relief（負債減壓）與 Liquidity Burn（流動性燃燒）。退休請求權或未來現金負擔的改善，不能掩蓋可用流動性被消耗的事實。designated / protected reserve（指定／受保護準備金）與 unrestricted / free cash（非受限／自由現金）必須分開：除非法律可得性、控制權與用途均可驗證，前者不得直接當成自由現金。

Market Handoff Test（市場接棒檢查）檢驗發行人縮手後是否仍有 independent demand（獨立市場需求）：價格與流動性仍能站住，接棒證據增加；一縮手即失守，issuer dependence（發行人依賴）仍高。它只改善需求品質判讀，不構成價格保證或交易指令。

---

## 三、可逆輪動的精確保全關係式

令 A（原核心資產）先換成 B（暫時承接資產），再換回 A：

`q_B = (q_A * A0_bid - C_out) / B0_ask`

`q_A_back = (q_B * (B1_bid + d_cash) - C_back) / A1_ask`

`R_cap = q_A_back / q_A`

- `q_A`：起點投入輪動的原核心資產單位數。
- `q_B`：扣除出程摩擦後取得的暫時承接資產單位數。
- `q_A_back`：完成回程後可買回的原核心資產單位數。
- `A0_bid`、`B0_ask`：出程使用的可成交 bid / ask（買價／賣價）。
- `B1_bid`、`A1_ask`：回程使用的可成交 bid / ask（買價／賣價）。
- `C_out`、`C_back`：出程與回程的全部可驗證摩擦，例如手續費、稅費、滑價與其他現金成本。
- `d_cash`：Cash Clock（現金時鐘）已確認、在券商帳戶實際可用的現金，不是宣告、應收或推測的配息。

`R_cap` 是 Capital Preservation Ratio（資本保全比）：

- `R_cap < 1`：原核心資產股數受到侵蝕。
- `R_cap = 1`：原核心資產股數完整保全。
- `R_cap > 1`：回程後原核心資產股數增厚。

真正問題不是途中領到多少配息，而是出去的每一單位核心資產，回程能否完整回來。輸入必須使用可驗證的成交或市場資料；沒有同時點、可執行的雙向報價與摩擦資料時，對回復性主張採 claim-scoped（主張範圍限定）`BLOCKED`。

---

## 四、兩個時間鐘

Entitlement Clock（權利時鐘）記錄何時已取得配息或其他現金權利；Cash Clock（現金時鐘）記錄何時該現金已實際存入且可在券商帳戶重新部署。

兩者不得互相替代。已取得權利但尚未實際可用的現金，不能納入 `d_cash`、回程購買力或 `R_cap`。若帳戶可用性、稅務扣留、付款失敗或延遲仍未驗證，該現金仍屬 Cash Clock（現金時鐘）`BLOCKED`。

---

## 五、近面額診斷與模式判讀

接近面額時，可用以下 mental arithmetic（心算）作 approximate diagnostic（近似診斷）：

`G0 = B0_ask - A0_bid`

`G1 = B1_bid - A1_ask`

`E_approx ≈ d_cash + G1 - G0 - c`

其中 `c` 是同口徑的總摩擦估計。`E_approx` 只用來快速辨識差價與收益是否可能足以覆蓋摩擦，不能取代 `R_cap`；它不保證單位數、可成交性或回程資產完整性。

收益型面額資產需要先判斷所處模式：

- Par Recovery Mode（面額修復模式）：原資產仍具有有意義的面額修復空間，資本判斷應把失去該修復的機會成本納入。
- Carry Harvest Mode（收益收割模式）：價格修復空間有限，已實現且可用的 carry（收益）在總報酬中較具主導性。

原資產仍在 Par Recovery Mode（面額修復模式）時，不得只因另一資產短期 carry（收益）較高就機械輪動。兩種模式都是研究語義，不是價格預測、固定門檻或資本指令。

---

## 六、部位與風險

Position size（部位大小）取決於 returnability（可回復性）、市場深度、滑價、回程流動性與整體投資組合風險。若完整來回輪動會增加回程失敗、價格衝擊或集中度風險，Partial Roll（部分輪動）是正常風險控制工具，不等於策略失敗。

所有部位判讀還須保留反證：發行人縮手後需求是否斷裂、reserve（準備金）是否可用、現金是否真的進入 Cash Clock（現金時鐘）、以及回程市場是否仍足以承接。缺少任何決定性的輸入時，只封鎖受影響的主張，不以推測補數。

---

## 七、治理鎖

本文件不得：

- 不得新增第七層，或修改正式六層的 weights（權重）、燈號 thresholds（閾值）或正式 `mNAV` 語義。
- 將 `R_cap`、`E_approx`、任何研究模式或市場接棒判讀升格為正式分數、燈號、門檻或自動交易 gate（關卡）。
- 修改 Production approval（正式生產批准）、External Action Authority（外部行動權限）或 Capital Decision Authority（資本決策權限）。
- 不得讓機器產生交易、下單、資金移動或帳戶操作權限。
- 將發行人政策、指定準備金、名目配息、短期報價或面額語義解讀為保證、到期還本或無風險本金保護。

最終資本決策永遠屬於使用者。
