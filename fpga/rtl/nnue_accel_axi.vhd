library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity nnue_accel_axi is
  port (
    s_axi_aclk    : in  std_logic;
    s_axi_aresetn : in  std_logic;
    s_axi_awaddr  : in  std_logic_vector(15 downto 0);
    s_axi_awvalid : in  std_logic;
    s_axi_awready : out std_logic;
    s_axi_wdata   : in  std_logic_vector(31 downto 0);
    s_axi_wstrb   : in  std_logic_vector(3 downto 0);
    s_axi_wvalid  : in  std_logic;
    s_axi_wready  : out std_logic;
    s_axi_bresp   : out std_logic_vector(1 downto 0);
    s_axi_bvalid  : out std_logic;
    s_axi_bready  : in  std_logic;
    s_axi_araddr  : in  std_logic_vector(15 downto 0);
    s_axi_arvalid : in  std_logic;
    s_axi_arready : out std_logic;
    s_axi_rdata   : out std_logic_vector(31 downto 0);
    s_axi_rresp   : out std_logic_vector(1 downto 0);
    s_axi_rvalid  : out std_logic;
    s_axi_rready  : in  std_logic
  );
end entity;

architecture rtl of nnue_accel_axi is
  signal clk  : std_logic;
  signal rstn : std_logic;


  

  -- 16 Parallel DSP MAC Lanes
  type signed_arr_16 is array (0 to 15) of signed(31 downto 0);
  signal mac_p     : signed_arr_16 := (others => (others => '0'));
  signal mac_bias  : signed_arr_16 := (others => (others => '0'));
  signal mac_a     : signed_arr_16 := (others => (others => '0'));
  signal mac_b     : signed(8 downto 0) := (others => '0');
  signal mac_ce    : std_logic := '0';
  signal mac_clr   : std_logic := '0';

  attribute use_dsp : string;
  attribute use_dsp of mac_p : signal is "yes";

  -- Feature RAM: 256 words x 32 bits (1024 bytes)
  type ram_256x32 is array (0 to 255) of std_logic_vector(31 downto 0);
  signal feat_ram : ram_256x32 := (others => (others => '0'));
  attribute ram_style : string;
  attribute ram_style of feat_ram : signal is "block";
  signal feat_rdata : std_logic_vector(31 downto 0) := (others => '0');
  signal feat_raddr : integer range 0 to 255 := 0;

  -- FC0 Weights: 8 Banks x 1024 words x 32 bits (32 KB total)
  type ram_1024x32 is array (0 to 1023) of std_logic_vector(31 downto 0);
  signal fc0_ram_0 : ram_1024x32 := (others => (others => '0'));
  signal fc0_ram_1 : ram_1024x32 := (others => (others => '0'));
  signal fc0_ram_2 : ram_1024x32 := (others => (others => '0'));
  signal fc0_ram_3 : ram_1024x32 := (others => (others => '0'));
  signal fc0_ram_4 : ram_1024x32 := (others => (others => '0'));
  signal fc0_ram_5 : ram_1024x32 := (others => (others => '0'));
  signal fc0_ram_6 : ram_1024x32 := (others => (others => '0'));
  signal fc0_ram_7 : ram_1024x32 := (others => (others => '0'));
  attribute ram_style of fc0_ram_0 : signal is "block";
  attribute ram_style of fc0_ram_1 : signal is "block";
  attribute ram_style of fc0_ram_2 : signal is "block";
  attribute ram_style of fc0_ram_3 : signal is "block";
  attribute ram_style of fc0_ram_4 : signal is "block";
  attribute ram_style of fc0_ram_5 : signal is "block";
  attribute ram_style of fc0_ram_6 : signal is "block";
  attribute ram_style of fc0_ram_7 : signal is "block";

  type rdata_banks is array (0 to 7) of std_logic_vector(31 downto 0);
  signal fc0_rdata : rdata_banks := (others => (others => '0'));
  signal fc0_raddr : integer range 0 to 1023 := 0;

  -- FC1 Weights: 512 words x 32 bits (2048 bytes)
  type ram_512x32 is array (0 to 511) of std_logic_vector(31 downto 0);
  signal fc1_ram : ram_512x32 := (others => (others => '0'));
  attribute ram_style of fc1_ram : signal is "block";
  signal fc1_rdata : std_logic_vector(31 downto 0) := (others => '0');
  signal fc1_raddr : integer range 0 to 511 := 0;

  -- Biases: 64 words x 32 bits (0..31 is FC0 biases, 32..63 is FC1 biases)
  type ram_64x32 is array (0 to 63) of std_logic_vector(31 downto 0);
  signal bias_ram : ram_64x32 := (others => (others => '0'));
  attribute ram_style of bias_ram : signal is "distributed";

  -- FC2 Weights: 32 words x 32 bits (128 bytes)
  signal fc2_weight : ram_64x32 := (others => (others => '0'));
  attribute ram_style of fc2_weight : signal is "distributed";
  signal bias_fc2 : std_logic_vector(31 downto 0) := (others => '0');

  -- Intermediate Buffers
  type ram_128x8 is array (0 to 127) of unsigned(7 downto 0);
  signal concat_buf : ram_128x8 := (others => (others => '0'));
  attribute ram_style of concat_buf : signal is "distributed";

  type signed_arr_32 is array (0 to 31) of signed(31 downto 0);
  signal fc0_out : signed_arr_32 := (others => (others => '0'));
  signal fc1_out : signed_arr_32 := (others => (others => '0'));

  signal skip_0   : signed(31 downto 0) := (others => '0');

  -- Control & Status Registers
  signal start_pulse    : std_logic := '0';
  signal busy_reg       : std_logic := '0';
  signal done_reg       : std_logic := '0';
  signal active_bucket  : integer range 0 to 7 := 0;
  signal eval_out_reg   : std_logic_vector(31 downto 0) := (others => '0');
  signal cycle_cnt_reg  : unsigned(31 downto 0) := (others => '0');

  -- Squarer & Scaler DSPs
  signal act_sqr_u14  : unsigned(13 downto 0) := (others => '0');
  signal act_sqr_prod : unsigned(27 downto 0) := (others => '0');
  attribute use_dsp of act_sqr_prod : signal is "yes";

  signal act_val_reg  : signed(31 downto 0) := (others => '0');
  signal lock_reg     : std_logic := '0';

  signal scale_in   : signed(31 downto 0) := (others => '0');
  signal scale_prod : signed(47 downto 0) := (others => '0');
  attribute use_dsp of scale_prod : signal is "yes";

  -- State Machine
  type fsm_state is (
    ST_IDLE,
    ST_FC0_P0_START,
    ST_FC0_P0_RUN,
    ST_FC0_P1_START,
    ST_FC0_P1_RUN,
    ST_ACT0_A,
    ST_ACT0_A1,
    ST_ACT0_B,
    ST_FC1_P0_START,
    ST_FC1_P0_RUN,
    ST_FC1_P1_START,
    ST_FC1_P1_RUN,
    ST_ACT1_A,
    ST_ACT1_A1,
    ST_ACT1_B,
    ST_FC2_START,
    ST_FC2_RUN,
    ST_SCALE_0,
    ST_SCALE_1,
    ST_DONE
  );
  signal state : fsm_state := ST_IDLE;

  signal k_cnt    : integer range 0 to 1027 := 0;
  signal act_idx  : integer range 0 to 31 := 0;
  signal fc1_m    : integer range 0 to 63 := 0;
  signal fc1_w    : integer range 0 to 3 := 0;
  signal fc2_n    : integer range 0 to 127 := 0;

begin

  clk  <= s_axi_aclk;
  rstn <= s_axi_aresetn;
  s_axi_awready <= '1';
  s_axi_wready  <= '1';
  s_axi_bresp   <= "00";
  s_axi_bvalid  <= s_axi_awvalid and s_axi_wvalid;
  s_axi_arready <= '1';
  s_axi_rresp   <= "00";
  s_axi_rvalid  <= s_axi_arvalid;


  -- 16 Parallel DSP MAC Lanes
  gen_macs: for i in 0 to 15 generate
    process(clk)
    begin
      if rising_edge(clk) then
        if mac_clr = '1' then
          mac_p(i) <= mac_bias(i);
        elsif mac_ce = '1' then
          mac_p(i) <= mac_p(i) + (resize(mac_a(i)(7 downto 0), 9) * mac_b);
        end if;
      end if;
    end process;
  end generate;

  -- Activation squarer DSP
  process(clk)
  begin
    if rising_edge(clk) then
      act_sqr_prod <= act_sqr_u14 * act_sqr_u14;
    end if;
  end process;

  -- Output scaling multiplier DSP
  process(clk)
  begin
    if rising_edge(clk) then
      scale_prod <= scale_in * to_signed(9600, 16);
    end if;
  end process;

  -- Synchronous Block RAM processes
  process(clk)
    variable apb_addr : std_logic_vector(15 downto 0);
    variable apb_we   : std_logic;
    variable waddr_10 : integer range 0 to 1023;
  begin
    if rising_edge(clk) then
      apb_addr := s_axi_awaddr;
      apb_we   := s_axi_awvalid and s_axi_wvalid;
      waddr_10 := to_integer(unsigned(apb_addr(11 downto 2)));

      -- Feature RAM
      if apb_we = '1' and apb_addr(15) = '0' and apb_addr >= X"0400" and apb_addr <= X"07FC" then
        feat_ram(to_integer(unsigned(apb_addr(9 downto 2)))) <= s_axi_wdata;
      end if;
      feat_rdata <= feat_ram(feat_raddr);

      -- FC1 Weight RAM
      if apb_we = '1' and apb_addr(15) = '0' and apb_addr >= X"1400" and apb_addr <= X"1BFF" then
        fc1_ram(to_integer(unsigned(apb_addr(10 downto 2)))) <= s_axi_wdata;
      end if;
      fc1_rdata <= fc1_ram(fc1_raddr);

      -- FC0 Weight RAM Banks (0x8000 to 0xFFFF)
      if apb_we = '1' and apb_addr(15) = '1' then
        case apb_addr(14 downto 12) is
          when "000" => fc0_ram_0(waddr_10) <= s_axi_wdata;
          when "001" => fc0_ram_1(waddr_10) <= s_axi_wdata;
          when "010" => fc0_ram_2(waddr_10) <= s_axi_wdata;
          when "011" => fc0_ram_3(waddr_10) <= s_axi_wdata;
          when "100" => fc0_ram_4(waddr_10) <= s_axi_wdata;
          when "101" => fc0_ram_5(waddr_10) <= s_axi_wdata;
          when "110" => fc0_ram_6(waddr_10) <= s_axi_wdata;
          when others => fc0_ram_7(waddr_10) <= s_axi_wdata;
        end case;
      end if;

      fc0_rdata(0) <= fc0_ram_0(fc0_raddr);
      fc0_rdata(1) <= fc0_ram_1(fc0_raddr);
      fc0_rdata(2) <= fc0_ram_2(fc0_raddr);
      fc0_rdata(3) <= fc0_ram_3(fc0_raddr);
      fc0_rdata(4) <= fc0_ram_4(fc0_raddr);
      fc0_rdata(5) <= fc0_ram_5(fc0_raddr);
      fc0_rdata(6) <= fc0_ram_6(fc0_raddr);
      fc0_rdata(7) <= fc0_ram_7(fc0_raddr);
    end if;
  end process;

  -- AXI-Lite Read process
  process(s_axi_araddr, done_reg, busy_reg, eval_out_reg, cycle_cnt_reg, active_bucket, lock_reg)
  begin
    if s_axi_araddr = X"0000" then
      s_axi_rdata <= X"5346" & "0000000000000" & done_reg & busy_reg & '0';
    elsif s_axi_araddr = X"0004" then
      s_axi_rdata <= eval_out_reg;
    elsif s_axi_araddr = X"0008" then
      s_axi_rdata <= std_logic_vector(cycle_cnt_reg);
    elsif s_axi_araddr = X"000C" then
      s_axi_rdata <= std_logic_vector(to_unsigned(active_bucket, 32));
    elsif s_axi_araddr = X"0010" then
      if lock_reg = '0' then
        s_axi_rdata <= X"00000001";
      else
        s_axi_rdata <= X"00000000";
      end if;
    else
      s_axi_rdata <= (others => '0');
    end if;
  end process;

  -- Main Compute State Machine and Distributed Memory Writes
  process(clk)
    variable addr       : std_logic_vector(15 downto 0);
    variable feat_b     : unsigned(7 downto 0);
    variable v_32       : signed(31 downto 0);
    variable u_v        : unsigned(31 downto 0);
    variable sqr_val    : unsigned(7 downto 0);
    variable clip_val   : unsigned(7 downto 0);
    variable s_shift    : unsigned(6 downto 0);
    variable fc2_w_byte : signed(7 downto 0);
  begin
    if rising_edge(clk) then
      if rstn = '0' then
        state         <= ST_IDLE;
        busy_reg      <= '0';
        done_reg      <= '0';
        lock_reg      <= '0';
        active_bucket <= 0;
        start_pulse   <= '0';
        cycle_cnt_reg <= (others => '0');
        eval_out_reg  <= (others => '0');
        feat_raddr    <= 0;
        fc0_raddr     <= 0;
        fc1_raddr     <= 0;
        mac_ce        <= '0';
        mac_clr       <= '0';
      else
        start_pulse <= '0';
        mac_ce      <= '0';
        mac_clr     <= '0';

        -- Atomic lock acquisition on read of 0x0010
        if s_axi_arvalid = '1' and s_axi_araddr = X"0010" then
          lock_reg <= '1';
        end if;

        -- APB Register and Distributed RAM writes
        if s_axi_awvalid = '1' and s_axi_wvalid = '1' then
          addr := s_axi_awaddr;
          if addr(15) = '0' then
            if addr = X"0000" then
              if s_axi_wdata(0) = '1' then
                start_pulse <= '1';
              end if;
              if s_axi_wdata(2) = '1' then
                done_reg <= '0';
              end if;
            elsif addr = X"000C" then
              active_bucket <= to_integer(unsigned(s_axi_wdata(2 downto 0)));
            elsif addr = X"0010" then
              lock_reg <= s_axi_wdata(0);
            elsif addr >= X"1000" and addr <= X"107F" then
              bias_ram(to_integer(unsigned(addr(6 downto 2)))) <= s_axi_wdata;
            elsif addr >= X"1080" and addr <= X"10FF" then
              bias_ram(32 + to_integer(unsigned(addr(6 downto 2)))) <= s_axi_wdata;
            elsif addr = X"1100" then
              bias_fc2 <= s_axi_wdata;
            elsif addr >= X"1200" and addr <= X"127F" then
              fc2_weight(to_integer(unsigned(addr(6 downto 2)))) <= s_axi_wdata;
            end if;
          end if;
        end if;

        -- State Machine
        case state is
          when ST_IDLE =>
            if start_pulse = '1' then
              busy_reg      <= '1';
              done_reg      <= '0';
              cycle_cnt_reg <= (others => '0');
              state         <= ST_FC0_P0_START;
            end if;

          -- ==========================================================
          -- FC0 Pass 0: Compute Output Channels 0..15 (Banks 0..3)
          -- ==========================================================
          when ST_FC0_P0_START =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            feat_raddr    <= 0;
            fc0_raddr     <= 0;
            k_cnt         <= 0;
            for i in 0 to 15 loop
              mac_bias(i) <= signed(bias_ram(i));
            end loop;
            mac_clr       <= '1';
            state         <= ST_FC0_P0_RUN;

          when ST_FC0_P0_RUN =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            mac_ce        <= '1';

            if k_cnt + 1 < 1024 then
              fc0_raddr  <= k_cnt + 1;
              feat_raddr <= (k_cnt + 1) / 4;
            end if;

            case k_cnt mod 4 is
              when 0 => feat_b := unsigned(feat_rdata(7 downto 0));
              when 1 => feat_b := unsigned(feat_rdata(15 downto 8));
              when 2 => feat_b := unsigned(feat_rdata(23 downto 16));
              when others => feat_b := unsigned(feat_rdata(31 downto 24));
            end case;
            mac_b <= signed('0' & feat_b);

            for b in 0 to 3 loop
              mac_a(b * 4 + 0) <= resize(signed(fc0_rdata(b)(7 downto 0)), 32);
              mac_a(b * 4 + 1) <= resize(signed(fc0_rdata(b)(15 downto 8)), 32);
              mac_a(b * 4 + 2) <= resize(signed(fc0_rdata(b)(23 downto 16)), 32);
              mac_a(b * 4 + 3) <= resize(signed(fc0_rdata(b)(31 downto 24)), 32);
            end loop;

            if k_cnt = 1023 then
              state <= ST_FC0_P1_START;
            else
              k_cnt <= k_cnt + 1;
            end if;

          -- ==========================================================
          -- FC0 Pass 1: Compute Output Channels 16..31 (Banks 4..7)
          -- ==========================================================
          when ST_FC0_P1_START =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            for i in 0 to 15 loop
              fc0_out(i) <= mac_p(i);
            end loop;
            feat_raddr <= 0;
            fc0_raddr  <= 0;
            k_cnt      <= 0;
            for i in 0 to 15 loop
              mac_bias(i) <= signed(bias_ram(16 + i));
            end loop;
            mac_clr <= '1';
            state   <= ST_FC0_P1_RUN;

          when ST_FC0_P1_RUN =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            mac_ce        <= '1';

            if k_cnt + 1 < 1024 then
              fc0_raddr  <= k_cnt + 1;
              feat_raddr <= (k_cnt + 1) / 4;
            end if;

            case k_cnt mod 4 is
              when 0 => feat_b := unsigned(feat_rdata(7 downto 0));
              when 1 => feat_b := unsigned(feat_rdata(15 downto 8));
              when 2 => feat_b := unsigned(feat_rdata(23 downto 16));
              when others => feat_b := unsigned(feat_rdata(31 downto 24));
            end case;
            mac_b <= signed('0' & feat_b);

            for b in 0 to 3 loop
              mac_a(b * 4 + 0) <= resize(signed(fc0_rdata(4 + b)(7 downto 0)), 32);
              mac_a(b * 4 + 1) <= resize(signed(fc0_rdata(4 + b)(15 downto 8)), 32);
              mac_a(b * 4 + 2) <= resize(signed(fc0_rdata(4 + b)(23 downto 16)), 32);
              mac_a(b * 4 + 3) <= resize(signed(fc0_rdata(4 + b)(31 downto 24)), 32);
            end loop;

            if k_cnt = 1023 then
              act_idx <= 0;
              state   <= ST_ACT0_A;
            else
              k_cnt <= k_cnt + 1;
            end if;

          -- ==========================================================
          -- ACT0: Compute SqrClippedReLU & ClippedReLU on Channels 0..31
          -- ==========================================================
          when ST_ACT0_A =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            if act_idx = 0 then
              for i in 0 to 15 loop
                fc0_out(16 + i) <= mac_p(i);
              end loop;
              skip_0 <= fc0_out(30) - mac_p(15);
            end if;

            act_val_reg <= fc0_out(act_idx);
            state       <= ST_ACT0_A1;

          when ST_ACT0_A1 =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            v_32 := act_val_reg;
            u_v  := unsigned(abs(v_32));
            if u_v >= 16384 then
              act_sqr_u14 <= (others => '0');
            else
              act_sqr_u14 <= u_v(13 downto 0);
            end if;
            state <= ST_ACT0_B;

          when ST_ACT0_B =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            v_32 := act_val_reg;
            u_v  := unsigned(abs(v_32));

            -- SqrClippedReLU
            if u_v >= 16384 then
              sqr_val := to_unsigned(127, 8);
            else
              s_shift := unsigned(act_sqr_prod(27 downto 21));
              if s_shift > 127 then
                sqr_val := to_unsigned(127, 8);
              else
                sqr_val := resize(s_shift, 8);
              end if;
            end if;
            concat_buf(act_idx) <= sqr_val;

            -- ClippedReLU
            if v_32(31) = '1' then
              clip_val := (others => '0');
            else
              if v_32(31 downto 7) > 127 then
                clip_val := to_unsigned(127, 8);
              else
                clip_val := unsigned(v_32(14 downto 7));
              end if;
            end if;
            concat_buf(32 + act_idx) <= clip_val;

            if act_idx = 31 then
              state <= ST_FC1_P0_START;
            else
              act_idx <= act_idx + 1;
              state   <= ST_ACT0_A;
            end if;

          -- ==========================================================
          -- FC1 Pass 0: Compute Channels 0..15 (64 steps x 4 words)
          -- ==========================================================
          when ST_FC1_P0_START =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            fc1_m     <= 0;
            fc1_w     <= 0;
            fc1_raddr <= 0;
            for i in 0 to 15 loop
              mac_bias(i) <= signed(bias_ram(32 + i));
            end loop;
            mac_clr <= '1';
            state   <= ST_FC1_P0_RUN;

          when ST_FC1_P0_RUN =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            mac_ce        <= '1';

            if fc1_w = 3 then
              if fc1_m < 63 then
                fc1_raddr <= (fc1_m + 1) * 8 + 0;
              end if;
            else
              fc1_raddr <= fc1_m * 8 + (fc1_w + 1);
            end if;

            mac_b <= signed('0' & concat_buf(fc1_m));

            for l in 0 to 15 loop
              mac_a(l) <= (others => '0');
            end loop;

            case fc1_w is
              when 0 =>
                mac_a(0) <= resize(signed(fc1_rdata(7 downto 0)), 32);
                mac_a(1) <= resize(signed(fc1_rdata(15 downto 8)), 32);
                mac_a(2) <= resize(signed(fc1_rdata(23 downto 16)), 32);
                mac_a(3) <= resize(signed(fc1_rdata(31 downto 24)), 32);
              when 1 =>
                mac_a(4) <= resize(signed(fc1_rdata(7 downto 0)), 32);
                mac_a(5) <= resize(signed(fc1_rdata(15 downto 8)), 32);
                mac_a(6) <= resize(signed(fc1_rdata(23 downto 16)), 32);
                mac_a(7) <= resize(signed(fc1_rdata(31 downto 24)), 32);
              when 2 =>
                mac_a(8)  <= resize(signed(fc1_rdata(7 downto 0)), 32);
                mac_a(9)  <= resize(signed(fc1_rdata(15 downto 8)), 32);
                mac_a(10) <= resize(signed(fc1_rdata(23 downto 16)), 32);
                mac_a(11) <= resize(signed(fc1_rdata(31 downto 24)), 32);
              when others =>
                mac_a(12) <= resize(signed(fc1_rdata(7 downto 0)), 32);
                mac_a(13) <= resize(signed(fc1_rdata(15 downto 8)), 32);
                mac_a(14) <= resize(signed(fc1_rdata(23 downto 16)), 32);
                mac_a(15) <= resize(signed(fc1_rdata(31 downto 24)), 32);
            end case;

            if fc1_w = 3 then
              fc1_w <= 0;
              if fc1_m = 63 then
                state <= ST_FC1_P1_START;
              else
                fc1_m <= fc1_m + 1;
              end if;
            else
              fc1_w <= fc1_w + 1;
            end if;

          -- ==========================================================
          -- FC1 Pass 1: Compute Channels 16..31 (64 steps x 4 words)
          -- ==========================================================
          when ST_FC1_P1_START =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            for i in 0 to 15 loop
              fc1_out(i) <= mac_p(i);
            end loop;
            fc1_m     <= 0;
            fc1_w     <= 0;
            fc1_raddr <= 4;
            for i in 0 to 15 loop
              mac_bias(i) <= signed(bias_ram(48 + i));
            end loop;
            mac_clr <= '1';
            state   <= ST_FC1_P1_RUN;

          when ST_FC1_P1_RUN =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            mac_ce        <= '1';

            if fc1_w = 3 then
              if fc1_m < 63 then
                fc1_raddr <= (fc1_m + 1) * 8 + 4;
              end if;
            else
              fc1_raddr <= fc1_m * 8 + 4 + (fc1_w + 1);
            end if;

            mac_b <= signed('0' & concat_buf(fc1_m));

            for l in 0 to 15 loop
              mac_a(l) <= (others => '0');
            end loop;

            case fc1_w is
              when 0 =>
                mac_a(0) <= resize(signed(fc1_rdata(7 downto 0)), 32);
                mac_a(1) <= resize(signed(fc1_rdata(15 downto 8)), 32);
                mac_a(2) <= resize(signed(fc1_rdata(23 downto 16)), 32);
                mac_a(3) <= resize(signed(fc1_rdata(31 downto 24)), 32);
              when 1 =>
                mac_a(4) <= resize(signed(fc1_rdata(7 downto 0)), 32);
                mac_a(5) <= resize(signed(fc1_rdata(15 downto 8)), 32);
                mac_a(6) <= resize(signed(fc1_rdata(23 downto 16)), 32);
                mac_a(7) <= resize(signed(fc1_rdata(31 downto 24)), 32);
              when 2 =>
                mac_a(8)  <= resize(signed(fc1_rdata(7 downto 0)), 32);
                mac_a(9)  <= resize(signed(fc1_rdata(15 downto 8)), 32);
                mac_a(10) <= resize(signed(fc1_rdata(23 downto 16)), 32);
                mac_a(11) <= resize(signed(fc1_rdata(31 downto 24)), 32);
              when others =>
                mac_a(12) <= resize(signed(fc1_rdata(7 downto 0)), 32);
                mac_a(13) <= resize(signed(fc1_rdata(15 downto 8)), 32);
                mac_a(14) <= resize(signed(fc1_rdata(23 downto 16)), 32);
                mac_a(15) <= resize(signed(fc1_rdata(31 downto 24)), 32);
            end case;

            if fc1_w = 3 then
              fc1_w <= 0;
              if fc1_m = 63 then
                act_idx <= 0;
                state   <= ST_ACT1_A;
              else
                fc1_m <= fc1_m + 1;
              end if;
            else
              fc1_w <= fc1_w + 1;
            end if;

          -- ==========================================================
          -- ACT1: Compute SqrClippedReLU & ClippedReLU on FC1
          -- ==========================================================
          when ST_ACT1_A =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            if act_idx = 0 then
              for i in 0 to 15 loop
                fc1_out(16 + i) <= mac_p(i);
              end loop;
            end if;

            act_val_reg <= fc1_out(act_idx);
            state       <= ST_ACT1_A1;

          when ST_ACT1_A1 =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            v_32 := act_val_reg;
            u_v  := unsigned(abs(v_32));
            if u_v >= 8192 then
              act_sqr_u14 <= (others => '0');
            else
              act_sqr_u14 <= u_v(13 downto 0);
            end if;
            state <= ST_ACT1_B;

          when ST_ACT1_B =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            v_32 := act_val_reg;
            u_v  := unsigned(abs(v_32));

            if u_v >= 8192 then
              sqr_val := to_unsigned(127, 8);
            else
              s_shift := unsigned(act_sqr_prod(25 downto 19));
              if s_shift > 127 then
                sqr_val := to_unsigned(127, 8);
              else
                sqr_val := resize(s_shift, 8);
              end if;
            end if;
            concat_buf(64 + act_idx) <= sqr_val;

            if v_32(31) = '1' then
              clip_val := (others => '0');
            else
              if v_32(31 downto 6) > 127 then
                clip_val := to_unsigned(127, 8);
              else
                clip_val := unsigned(v_32(13 downto 6));
              end if;
            end if;
            concat_buf(96 + act_idx) <= clip_val;

            if act_idx = 31 then
              state <= ST_FC2_START;
            else
              act_idx <= act_idx + 1;
              state   <= ST_ACT1_A;
            end if;

          -- ==========================================================
          -- FC2: 128 weights into Lane 0
          -- ==========================================================
          when ST_FC2_START =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            fc2_n         <= 0;
            mac_bias(0)   <= signed(bias_fc2);
            mac_clr       <= '1';
            state         <= ST_FC2_RUN;

          when ST_FC2_RUN =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            mac_ce        <= '1';
            mac_b         <= signed('0' & concat_buf(fc2_n));

            case fc2_n mod 4 is
              when 0 => fc2_w_byte := signed(fc2_weight(fc2_n / 4)(7 downto 0));
              when 1 => fc2_w_byte := signed(fc2_weight(fc2_n / 4)(15 downto 8));
              when 2 => fc2_w_byte := signed(fc2_weight(fc2_n / 4)(23 downto 16));
              when others => fc2_w_byte := signed(fc2_weight(fc2_n / 4)(31 downto 24));
            end case;

            for l in 0 to 15 loop
              mac_a(l) <= (others => '0');
            end loop;
            mac_a(0) <= resize(fc2_w_byte, 32);

            if fc2_n = 127 then
              state <= ST_SCALE_0;
            else
              fc2_n <= fc2_n + 1;
            end if;

          -- ==========================================================
          -- SCALE: Multiply by 9600 and divide by 16384 (shift right 14)
          -- ==========================================================
          when ST_SCALE_0 =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            scale_in      <= mac_p(0) + skip_0;
            state         <= ST_SCALE_1;

          when ST_SCALE_1 =>
            cycle_cnt_reg <= cycle_cnt_reg + 1;
            if scale_prod(47) = '1' then
              eval_out_reg <= std_logic_vector(shift_right(scale_prod + 16383, 14)(31 downto 0));
            else
              eval_out_reg <= std_logic_vector(shift_right(scale_prod, 14)(31 downto 0));
            end if;
            done_reg <= '1';
            busy_reg <= '0';
            state    <= ST_DONE;

          when ST_DONE =>
            if start_pulse = '1' then
              busy_reg      <= '1';
              done_reg      <= '0';
              cycle_cnt_reg <= (others => '0');
              state         <= ST_FC0_P0_START;
            end if;

        end case;
      end if;
    end if;
  end process;

end architecture;
