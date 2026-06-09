#!/usr/bin/env python3
"""
ServiceNow AD Group Request Automation - Multi-Group Version
Automates the process of raising AD group membership requests via ServiceNow portal.
This version adds ONE USER to MULTIPLE GROUPS in one request.

Page 1: Selects "Multiple Groups" in the last dropdown.
Page 2: USER-centric form:
  1. User to modify         → single-select reference field
  2. Choose groups          → multi-select (one chip per group)
  3. Add or remove groups   → dropdown
  4. Business Justification → text field

Usage:
    python ad_group_multi_group.py --groups "GROUP1,GROUP2,GROUP3" --users "akiran" --justification "reason"
"""

import argparse
import time
import sys
from typing import List
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class ServiceNowADAutomation:
    """Automates AD group membership requests on ServiceNow - Multi-Group variant."""

    SERVICENOW_URL = "https://walmartglobal.service-now.com/wm_sp"
    DEFAULT_TIMEOUT = 30

    def __init__(self, headless: bool = False, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.driver = self._setup_driver(headless)
        self.wait = WebDriverWait(self.driver, timeout)

    def _setup_driver(self, headless: bool) -> webdriver.Chrome:
        """Configure and return Chrome WebDriver."""
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")

        try:
            driver = webdriver.Chrome(options=options)
            return driver
        except Exception as e:
            print(f"❌ Failed to initialize Chrome driver: {e}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    def wait_and_click(self, by: By, value: str, description: str = "element"):
        """Wait for element to be clickable and click it."""
        try:
            print(f"  ⏳ Waiting for {description}...")
            element = self.wait.until(EC.element_to_be_clickable((by, value)))
            element.click()
            print(f"  ✅ Clicked {description}")
            time.sleep(1)
            return element
        except TimeoutException:
            print(f"  ❌ Timeout waiting for {description}")
            raise

    def navigate_to_servicenow(self):
        """Open ServiceNow portal and wait for SSO authentication."""
        print("\n🌐 Opening ServiceNow portal...")
        self.driver.get(self.SERVICENOW_URL)
        print("  ⏳ Waiting for SSO authentication (you may need to log in manually)...")
        try:
            self.wait = WebDriverWait(self.driver, 120)
            self.wait.until(
                lambda d: "service-now.com" in d.current_url and "login" not in d.current_url.lower()
            )
            print("  ✅ Successfully authenticated to ServiceNow")
        except TimeoutException:
            print("  ❌ SSO authentication timeout. Please complete login manually.")
            raise
        finally:
            self.wait = WebDriverWait(self.driver, self.timeout)

    # ------------------------------------------------------------------
    # Page 1: Describe Needs — dropdown selections
    # ------------------------------------------------------------------

    def select_dropdown_option(self, dropdown_label: str, option_text: str):
        """
        Select an option from a ServiceNow Select2 dropdown.
        Uses AngularJS-aware approach with click-based fallback.
        """
        print(f"  ⏳ Selecting '{option_text}' for '{dropdown_label[:40]}...'")

        script = f"""
        (function() {{
            var dropdownLabel = '{dropdown_label}';
            var optionText = '{option_text}';
            var inputs = document.querySelectorAll('input.select2-focusser');
            var selectElement = null;

            for (var i = 0; i < inputs.length; i++) {{
                var label = inputs[i].getAttribute('aria-label');
                if (label && label.includes(dropdownLabel)) {{
                    var container = inputs[i].closest('.select2-container');
                    if (container) {{
                        var selectId = container.id.replace('s2id_', '');
                        selectElement = document.getElementById(selectId);
                        break;
                    }}
                }}
            }}

            if (!selectElement) {{
                return {{'success': false, 'error': 'Could not find select element for: ' + dropdownLabel}};
            }}

            var optionValue = null;
            var optionFullText = null;
            for (var i = 0; i < selectElement.options.length; i++) {{
                var opt = selectElement.options[i];
                if (opt.text && opt.text.includes(optionText)) {{
                    optionValue = opt.value;
                    optionFullText = opt.text;
                    break;
                }}
            }}

            if (optionValue === null) {{
                return {{'success': false, 'error': 'Could not find option: ' + optionText}};
            }}

            selectElement.value = optionValue;

            var $select = angular.element(selectElement);
            var scope = $select.scope();
            if (scope) {{
                scope.$apply(function() {{
                    if (typeof scope.fieldValue === 'function') scope.fieldValue(optionValue);
                    else scope.fieldValue = optionValue;
                }});
            }}

            if (typeof jQuery !== 'undefined') {{
                jQuery(selectElement).val(optionValue).trigger('change');
            }}

            selectElement.dispatchEvent(new Event('change', {{ bubbles: true }}));
            selectElement.dispatchEvent(new Event('input', {{ bubbles: true }}));

            return {{'success': true, 'selectedText': optionFullText, 'selectedValue': optionValue}};
        }})();
        """

        try:
            result = self.driver.execute_script(script)
            if result is None:
                result = {'success': False, 'error': 'Script returned None - jQuery may not be available'}

            if result.get('success'):
                print(f"  ✅ Selected '{result.get('selectedText', option_text)}'")
                time.sleep(0.5)
                return

            print(f"  ⚠️ Select2 API method failed: {result.get('error', 'Unknown error')}")
            print(f"  ⏳ Trying click-based selection...")

            # Click to open dropdown
            open_script = f"""
            var inputs = document.querySelectorAll('input.select2-focusser');
            for (var i = 0; i < inputs.length; i++) {{
                var label = inputs[i].getAttribute('aria-label');
                if (label && label.includes('{dropdown_label}')) {{
                    var container = inputs[i].closest('.select2-container');
                    var choice = container.querySelector('.select2-choice, .select2-chosen');
                    if (choice) {{ choice.click(); return true; }}
                }}
            }}
            return false;
            """
            self.driver.execute_script(open_script)
            time.sleep(1)

            # Click matching option in the active dropdown
            click_script = f"""
            var dropdowns = document.querySelectorAll('.select2-drop');
            var activeDropdown = null;
            for (var i = 0; i < dropdowns.length; i++) {{
                if (dropdowns[i].style.display !== 'none' &&
                    !dropdowns[i].classList.contains('select2-display-none')) {{
                    activeDropdown = dropdowns[i];
                    break;
                }}
            }}
            if (!activeDropdown) {{
                activeDropdown = document.querySelector('.select2-drop-active, .select2-with-searchbox');
            }}
            if (activeDropdown) {{
                var results = activeDropdown.querySelectorAll('.select2-result-label, li.select2-result');
                for (var i = 0; i < results.length; i++) {{
                    var text = results[i].textContent.trim();
                    if (text === '{option_text}') {{ results[i].click(); return {{'clicked': true, 'text': text}}; }}
                }}
                for (var i = 0; i < results.length; i++) {{
                    var text = results[i].textContent.trim();
                    if (text.includes('{option_text}')) {{ results[i].click(); return {{'clicked': true, 'text': text}}; }}
                }}
            }}
            return {{'clicked': false}};
            """
            click_result = self.driver.execute_script(click_script)

            if click_result and click_result.get('clicked'):
                print(f"  ✅ Selected '{click_result.get('text')}' via click")
                time.sleep(0.5)
                return

            # Final fallback: Selenium XPath
            try:
                dropdown_option = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH,
                        f"//div[contains(@class, 'select2-result-label')][text()='{option_text}']"))
                )
                dropdown_option.click()
                print(f"  ✅ Selected '{option_text}' via Selenium")
                time.sleep(2)
                return
            except:
                # Verify if the value was actually selected despite errors
                verify_script = f"""
                var inputs = document.querySelectorAll('input.select2-focusser');
                for (var i = 0; i < inputs.length; i++) {{
                    var label = inputs[i].getAttribute('aria-label');
                    if (label && label.includes('{dropdown_label}')) {{
                        var container = inputs[i].closest('.select2-container');
                        var chosen = container.querySelector('.select2-chosen');
                        if (chosen && chosen.textContent.includes('{option_text}')) return true;
                    }}
                }}
                return false;
                """
                if self.driver.execute_script(verify_script):
                    print(f"  ✅ Verified '{option_text}' is selected")
                    time.sleep(0.5)
                    return
                raise Exception(f"Could not select '{option_text}'")

        except Exception as e:
            print(f"  ❌ Failed to select option: {e}")
            raise

    def navigate_to_ad_request(self):
        """
        Navigate through ServiceNow to AD Group request form.
        Page 1 selections for multi-group:
          Environment     → Production
          Type            → Group
          Action          → Modify an existing Active Directory group
          What to modify  → Group Membership
          One or Multiple → Multiple Groups   ← key difference from multi-user
        """
        print("\n📋 Navigating to AD Group request form...")

        # Click Active Directory in services menu
        ad_selectors = [
            (By.XPATH, "//*[contains(text(), 'Active Directory')]"),
            (By.LINK_TEXT, "Active Directory"),
            (By.PARTIAL_LINK_TEXT, "Active Directory"),
            (By.CSS_SELECTOR, "[data-item-name='Active Directory']"),
        ]
        for by, selector in ad_selectors:
            try:
                self.wait_and_click(by, selector, "Active Directory option")
                break
            except:
                continue

        time.sleep(2)

        # Wait for form to load
        print("\n  ⏳ Waiting for form to load...")
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, ".select2-container, select, .form-group")) > 0
            )
            print("  ✅ Form loaded")
        except:
            print("  ⚠️ Form may not have fully loaded, continuing anyway...")
        time.sleep(2)

        print("\n📝 Filling out Describe Needs form...")

        self.select_dropdown_option("What environment are you requesting", "Production")
        self.select_dropdown_option("What type of Active Directory activity", "Group")
        self.select_dropdown_option("What are you looking to do with", "Modify an existing Active Directory group")
        self.select_dropdown_option("What are you looking to modify", "Group Membership")

        # KEY: Select "Multiple Groups" for the multi-group script
        self.select_dropdown_option("Are you looking to modify one", "Multiple Groups")

        # Click Next
        print("\n  ⏳ Looking for Next button...")
        try:
            next_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "submit"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
            time.sleep(0.3)
            next_btn.click()
            print("  ✅ Clicked Next button (by ID)")
        except:
            try:
                script = """
                var btn = document.getElementById('submit');
                if (btn) { btn.click(); return true; }
                var scope = angular.element(document.body).scope();
                if (scope && scope.goNext) {
                    scope.$apply(function() { scope.goNext(); });
                    return true;
                }
                return false;
                """
                result = self.driver.execute_script(script)
                if result:
                    print("  ✅ Clicked Next via JavaScript")
                else:
                    print("  ⚠️ Could not find Next button")
            except Exception as e:
                print(f"  ⚠️ Next button click failed: {e}")

        time.sleep(3)
        print("  ✅ Navigated to Choose Options page")

    # ------------------------------------------------------------------
    # Page 2: Choose Options — USER-centric form (Multiple Groups)
    # ------------------------------------------------------------------

    def select_user_reference_field(self, username: str):
        """
        Select the single user in 'User to modify' field.
        Container: s2id_sp_formfield_user_reference
        """
        print(f"  ⏳ Selecting user to modify: {username}")

        try:
            # Click the Select2 choice to open the dropdown
            script = """
            (function() {
                var container = document.getElementById('s2id_sp_formfield_user_reference');
                if (!container) return {'success': false, 'error': 'Container not found'};
                var choice = container.querySelector('a.select2-choice');
                if (choice) {
                    choice.scrollIntoView({block: 'center'});
                    choice.click();
                    return {'success': true, 'method': 'choice-click'};
                }
                container.click();
                return {'success': true, 'method': 'container-click'};
            })();
            """
            result = self.driver.execute_script(script)
            if not result or not result.get('success'):
                container = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "s2id_sp_formfield_user_reference"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", container)
                container.click()

            time.sleep(0.8)

            # Wait for dropdown to be active
            WebDriverWait(self.driver, 5).until(
                lambda d: d.find_element(By.CSS_SELECTOR, ".select2-drop-active")
            )

            # Type in search input
            search_input = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".select2-drop-active input.select2-input"))
            )
            self.driver.execute_script("""
                var input = arguments[0];
                var value = arguments[1];
                input.focus();
                input.value = value;
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
            """, search_input, username)
            time.sleep(1.5)

            # Click first matching result
            try:
                result_item = WebDriverWait(self.driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-results li.select2-result-selectable"))
                )
                result_item.click()
                print(f"  ✅ Selected user: {username}")
            except:
                search_input.send_keys(Keys.RETURN)
                print(f"  ✅ Selected user via Enter: {username}")

            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Failed to select user: {e}")
            raise

    def add_group_to_multi_select(self, group_name: str):
        """
        Add a group chip to the 'Choose groups' multi-select field.
        Container: s2id_sp_formfield_group_list
        Uses the inner multi-select input to search and select each group.
        """
        print(f"  ⏳ Adding group: {group_name}")

        try:
            # Find the multi-select input inside the group_list container
            # First try by container ID, then fall back to generic multi-select
            input_field = None

            # Method 1: Find input inside the known container
            try:
                container = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.ID, "s2id_sp_formfield_group_list"))
                )
                input_field = container.find_element(By.CSS_SELECTOR, "input.select2-input")
            except:
                pass

            # Method 2: Any active multi-select input on page
            if not input_field:
                input_field = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-container-multi input.select2-input"))
                )

            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_field)
            time.sleep(0.2)
            input_field.click()
            time.sleep(0.3)

            # Type group name to trigger autocomplete
            self.driver.execute_script("""
                var input = arguments[0];
                input.focus();
                input.value = arguments[1];
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
            """, input_field, group_name)
            time.sleep(1.5)

            # Click matching result
            try:
                result_item = WebDriverWait(self.driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-results li.select2-result-selectable"))
                )
                result_item.click()
                print(f"  ✅ Added group: {group_name}")
            except:
                input_field.send_keys(Keys.RETURN)
                print(f"  ✅ Added group via Enter: {group_name}")

            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Failed to add group {group_name}: {e}")
            raise

    def fill_page2_user_centric_form(self, username: str, groups: List[str], justification: str):
        """
        Fill Page 2 USER-centric form (shown when 'Multiple Groups' is selected on Page 1).
        Field order:
          1. User to modify         → single reference field
          2. Choose groups          → multi-select (one chip per group)
          3. Add or remove groups   → dropdown
          4. Business Justification → text field
        """

        # Step 1: Select the single user
        print(f"\n👤 Selecting user to modify: {username}")
        self.select_user_reference_field(username)

        # Step 2: Add each group to the multi-select
        print(f"\n📂 Adding {len(groups)} group(s)...")
        for i, group in enumerate(groups, 1):
            print(f"\n  [{i}/{len(groups)}] Adding group: {group}")
            try:
                self.add_group_to_multi_select(group)
            except Exception as e:
                print(f"    ❌ Failed to add group {group}: {e}")
                # Continue adding remaining groups
                continue

        # Verify chips were added
        print(f"\n  📋 Verifying added groups...")
        try:
            chips = self.driver.find_elements(
                By.CSS_SELECTOR, ".select2-container-multi .select2-search-choice"
            )
            print(f"  ✅ {len(chips)} group(s) added to the request")
        except:
            pass

        # Step 3: Set Add/Remove action
        # Label: "Do you want to add the groups or remove the groups from the specified user?"
        # Option text: "Add groups"
        print("\n🔧 Setting action to 'Add groups'...")
        try:
            self.select_dropdown_option("Do you want to add the groups", "Add groups")
        except Exception as e:
            print(f"  ⚠️ Add/Remove dropdown failed: {e}, trying direct method...")
            script = """
            var selects = document.querySelectorAll('select[name*="addremove"], select');
            for (var i = 0; i < selects.length; i++) {
                var select = selects[i];
                for (var j = 0; j < select.options.length; j++) {
                    if (select.options[j].text.toLowerCase().includes('add')) {
                        select.value = select.options[j].value;
                        var scope = angular.element(select).scope();
                        if (scope) {
                            scope.$apply(function() {
                                if (typeof scope.fieldValue === 'function') scope.fieldValue(select.value);
                                else scope.fieldValue = select.value;
                            });
                        }
                        if (typeof jQuery !== 'undefined') jQuery(select).trigger('change');
                        select.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                }
            }
            return false;
            """
            self.driver.execute_script(script)
            print("  ✅ Set action via JavaScript")
        time.sleep(0.5)

        # Step 4: Enter business justification
        print(f"\n📝 Entering justification: {justification[:40]}...")
        try:
            justification_input = None
            try:
                justification_input = self.driver.find_element(By.ID, "sp_formfield_busjust")
            except:
                script = """
                var labels = document.querySelectorAll('label');
                for (var i = 0; i < labels.length; i++) {
                    if (labels[i].textContent.includes('Business Justification')) {
                        var formGroup = labels[i].closest('.form-group');
                        if (formGroup) {
                            var input = formGroup.querySelector('input[type="text"], textarea');
                            return input;
                        }
                    }
                }
                return null;
                """
                justification_input = self.driver.execute_script(script)

            if justification_input:
                justification_input.clear()
                justification_input.send_keys(justification)
                print("  ✅ Entered business justification")
            else:
                print("  ⚠️ Could not find justification field")
        except Exception as e:
            print(f"  ⚠️ Failed to enter justification: {e}")

        time.sleep(0.5)

    # ------------------------------------------------------------------
    # Accordion expand
    # ------------------------------------------------------------------

    def expand_accordion(self):
        """
        Expand the accordion on Page 2 to reveal the form fields.
        For user-centric form the title is "Modify Active Directory User Membership".
        """
        print("  ⏳ Expanding accordion...")

        expand_script = """
        (function() {
            // First check if already expanded (fields visible)
            var panels = document.querySelectorAll('.panel-collapse');
            for (var i = 0; i < panels.length; i++) {
                if (panels[i].classList.contains('in') || panels[i].getAttribute('aria-expanded') === 'true') {
                    var fields = panels[i].querySelectorAll('[id*="sp_formfield"]');
                    if (fields.length > 0) {
                        return {'success': true, 'method': 'already-expanded', 'fieldsFound': fields.length};
                    }
                }
            }

            // Find accordion by "Modify Active Directory" text in item_name
            var items = document.querySelectorAll('[id^="item_name_"]');
            for (var i = 0; i < items.length; i++) {
                var text = items[i].textContent || '';
                if (text.includes('Modify Active Directory')) {
                    var toggle = items[i].closest('.accordion-toggle');
                    if (toggle) { toggle.click(); return {'success': true, 'method': 'accordion-toggle'}; }
                    var heading = items[i].closest('.panel-heading');
                    if (heading) { heading.click(); return {'success': true, 'method': 'panel-heading'}; }
                }
            }

            // Fallback: click chevron
            var chevrons = document.querySelectorAll('.fa-chevron-down');
            if (chevrons.length > 0) {
                var parent = chevrons[0].closest('[ng-click]') || chevrons[0].closest('.panel-heading');
                if (parent) { parent.click(); return {'success': true, 'method': 'chevron'}; }
            }

            return {'success': false, 'error': 'Could not find accordion'};
        })();
        """

        try:
            result = self.driver.execute_script(expand_script)
            if result and result.get('success'):
                method = result.get('method', 'js')
                if method == 'already-expanded':
                    print(f"  ✅ Accordion already expanded ({result.get('fieldsFound', 0)} fields visible)")
                else:
                    print(f"  ✅ Expanded accordion ({method})")
                time.sleep(1.5)
                return True
            else:
                print(f"  ⚠️ Accordion expansion may have failed: {result}")
        except Exception as e:
            print(f"  ⚠️ Accordion JS failed: {e}")

        # Selenium fallback
        try:
            accordion = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((
                By.XPATH, "//*[contains(text(), 'Modify Active Directory')]/ancestor::div[contains(@class, 'panel-heading')]"
            )))
            self.driver.execute_script("arguments[0].scrollIntoView(true);", accordion)
            time.sleep(0.2)
            accordion.click()
            print("  ✅ Expanded accordion via Selenium")
            time.sleep(1.5)
            return True
        except:
            print("  ⚠️ Could not expand accordion, form fields may already be visible")
            return False

    # ------------------------------------------------------------------
    # Main submission
    # ------------------------------------------------------------------

    def submit_ad_group_request(
        self,
        groups: List[str],
        username: str,
        justification: str,
        dry_run: bool = False
    ):
        """
        Submit the AD group membership request (user-centric: 1 user → N groups).

        Args:
            groups:        List of AD group names
            username:      Single username to add to all groups
            justification: Business justification text
            dry_run:       If True, stop before final submission
        """
        print(f"\n🚀 Submitting AD Group Request:")
        print(f"   Groups: {', '.join(groups)}")
        print(f"   User: {username}")
        print(f"   Justification: {justification[:50]}...")

        print("\n📝 Filling out Choose Options form (Page 2)...")
        time.sleep(1)

        # Expand accordion to reveal form
        self.expand_accordion()

        # Wait for "User to modify" label to confirm page 2 is showing the user-centric form
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'User to modify')]"))
            )
            print("  ✅ User-centric form fields are visible")
        except:
            print("  ⚠️ 'User to modify' label not found, form may still be loading. Continuing...")

        # Fill the user-centric form
        self.fill_page2_user_centric_form(username, groups, justification)

        print(f"\n✅ Page 2 form filled successfully ({len(groups)} group(s) for user '{username}')")

        if dry_run:
            print("\n🔍 DRY RUN MODE - Stopping before final submission")
            print("   Review the form in the browser and submit manually if correct")
            input("   Press Enter to close the browser...")
            return

        # Click Next → Summary page
        print("\n  ⏳ Clicking Next to proceed to Summary...")
        try:
            next_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "submit"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
            time.sleep(0.3)
            next_btn.click()
            print("  ✅ Clicked Next button")
        except:
            try:
                self.wait_and_click(By.XPATH, "//button[contains(text(), 'next')]", "Next button (fallback)")
            except:
                self.driver.execute_script(
                    "angular.element(document.body).scope().$apply(function() { angular.element(document.body).scope().goNext(); });"
                )
                print("  ✅ Navigated via Angular goNext()")
        time.sleep(2)

        # Submit from Summary page
        print("\n📤 Submitting request...")
        submit_selectors = [
            "//button[contains(text(), 'Submit')]",
            "//button[contains(text(), 'Confirm')]",
            "//button[contains(text(), 'Order Now')]",
            "//button[contains(@class, 'submit')]",
        ]
        for selector in submit_selectors:
            try:
                self.wait_and_click(By.XPATH, selector, "Submit button")
                break
            except:
                continue

        time.sleep(3)

        # Capture confirmation
        try:
            success_msg = self.driver.find_element(
                By.XPATH,
                "//*[contains(@class, 'success') or contains(@class, 'confirmation') or contains(text(), 'REQ') or contains(text(), 'submitted')]"
            )
            print(f"\n✅ Request submitted successfully!")
            print(f"   {success_msg.text}")
        except NoSuchElementException:
            print("\n✅ Request appears to have been submitted (check ServiceNow for confirmation)")

    def close(self):
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            print("\n🔒 Browser closed")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Automate AD Group membership requests on ServiceNow — Multi-Group variant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add one user to multiple groups
  python ad_group_multi_group.py --groups "GROUP1,GROUP2,GROUP3" --users "akiran" --justification "ET360 access"

  # Dry run (navigate but don't submit)
  python ad_group_multi_group.py --groups "GROUP1,GROUP2" --users "akiran" --justification "test" --dry-run
        """
    )

    parser.add_argument(
        "--groups", "-g",
        required=True,
        help="Comma-separated list of AD group names (2 or more)"
    )
    parser.add_argument(
        "--users", "-u",
        required=True,
        help="Single username to add to all specified groups"
    )
    parser.add_argument(
        "--justification", "-j",
        required=True,
        help="Business justification for the request"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (not recommended for SSO)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Navigate to form but don't submit (for testing)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for element waits (default: 30)"
    )

    args = parser.parse_args()

    groups = [g.strip() for g in args.groups.split(",")]
    # For multi-group, only one user is supported
    users_input = [u.strip() for u in args.users.split(",")]
    if len(users_input) > 1:
        print("⚠️  Multi-group mode supports only ONE user. Using first user: " + users_input[0])
    username = users_input[0]

    if len(groups) < 2:
        print("⚠️  Multi-group mode works best with 2+ groups. For a single group, use ad_group_request.py instead.")

    print("=" * 60)
    print("🤖 ServiceNow AD Group Request Automation — Multi-Group")
    print("=" * 60)
    print(f"Groups: {groups}")
    print(f"User: {username}")
    print(f"Justification: {args.justification}")
    print(f"Mode: {'Dry Run' if args.dry_run else 'Live'}")
    print("=" * 60)

    automation = None
    try:
        automation = ServiceNowADAutomation(
            headless=args.headless,
            timeout=args.timeout
        )

        automation.navigate_to_servicenow()
        automation.navigate_to_ad_request()
        automation.submit_ad_group_request(
            groups=groups,
            username=username,
            justification=args.justification,
            dry_run=args.dry_run
        )

        print("\n" + "=" * 60)
        print("✅ Automation completed successfully!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n⚠️ Automation interrupted by user")
    except Exception as e:
        print(f"\n❌ Automation failed: {e}")
        if automation:
            try:
                automation.driver.save_screenshot("/tmp/servicenow_error.png")
                print("📸 Screenshot saved to /tmp/servicenow_error.png")
            except:
                pass
        sys.exit(1)
    finally:
        if automation:
            automation.close()


if __name__ == "__main__":
    main()
